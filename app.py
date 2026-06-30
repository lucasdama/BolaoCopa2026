from flask import Flask, render_template, request, redirect, url_for, flash, session
import os
import sqlite3
import psycopg2
import re
from psycopg2.extras import DictCursor
from datetime import datetime, timedelta
from datetime import timezone

# Brasil aboliu horário de verão em 2019; BRT = UTC-3 fixo.
TIMEZONE_BRASILIA = timezone(timedelta(hours=-3))
from pontuacao import calcular_pontos, multiplicador_da_fase
from werkzeug.security import generate_password_hash, check_password_hash
from flask import jsonify, session
from chaveamento import atualizar_chaveamento_completo

app = Flask(__name__)
app.secret_key = 'chave_secreta_copa_2026_super_protegida'

# 🎛️ FUNÇÃO INTELIGENTE DE CONEXÃO MULTI-BANCO
def obter_conexao_db():
    url_banco = os.environ.get('DATABASE_URL')
    
    if url_banco:
        # CONEXÃO PRODUÇÃO (POSTGRESQL NA RENDER)
        # O link interno da Render às vezes precisa desse ajuste de sslmode
        if "sslmode=" not in url_banco:
            url_banco += "?sslmode=prefer"
        conn = psycopg2.connect(url_banco)
        return conn
    else:
        # CONEXÃO LOCAL (SQLITE NO SEU PC)
        conn = sqlite3.connect('bolao.db')
        conn.row_factory = sqlite3.Row
        return conn

# 📊 TRATAMENTO DOS CURSORES CONFORME O BANCO ATIVO
def obter_cursor(conn):
    if os.environ.get('DATABASE_URL'):
        return conn.cursor(cursor_factory=DictCursor)
    else:
        return conn.cursor()

def eh_postgres(conn):
    return conn.__class__.__module__.startswith('psycopg2')

# 📝 ADAPTADOR DINÂMICO DE QUERIES (?, ? vs %s, %s)
def preparar_query(query):
    if os.environ.get('DATABASE_URL'):
        query = re.sub(r'--.*$', '', query, flags=re.MULTILINE)
        # psycopg2 usa % para placeholders; % literais em LIKE precisam ser escapados.
        query = query.replace('%', '%%')
        query = re.sub(r'(?<!\w)\?(?!\w)', '%s', query)
    return query

_ultimo_check_auto_inicio = datetime.min

def auto_iniciar_partidas():
    """Verifica partidas 'Pendente' cujo horário já passou e as marca como 'Em Andamento'."""
    global _ultimo_check_auto_inicio
    # Usa horário de Brasília (America/Sao_Paulo) para comparar com data_hora salva em BRT.
    # O servidor Render roda em UTC; sem essa conversão, datetime.now() estaria 3h adiantado.
    agora = datetime.now(TIMEZONE_BRASILIA).replace(tzinfo=None)

    # Só verifica uma vez por minuto para não bater no banco a cada request
    if (agora - _ultimo_check_auto_inicio).total_seconds() < 60:
        return
    _ultimo_check_auto_inicio = agora

    try:
        conn = obter_conexao_db()
        cursor = obter_cursor(conn)
        query = preparar_query("SELECT jogo_id, data_hora FROM jogos WHERE status = 'Pendente'")
        cursor.execute(query)
        partidas_pendentes = cursor.fetchall()

        ids_para_iniciar = []
        for p in partidas_pendentes:
            data_str = str(p['data_hora']).strip()
            horario_jogo = None
            for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%d/%m/%Y %H:%M'):
                try:
                    horario_jogo = datetime.strptime(data_str, fmt)
                    break
                except ValueError:
                    continue
            if horario_jogo and agora >= horario_jogo:
                ids_para_iniciar.append(p['jogo_id'])

        if ids_para_iniciar:
            for jid in ids_para_iniciar:
                q = preparar_query("UPDATE jogos SET status = 'Em Andamento' WHERE jogo_id = ?")
                cursor.execute(q, (jid,))
                print(f"[AUTO] Partida {jid} iniciada automaticamente às {agora.strftime('%H:%M:%S')}")
            conn.commit()

        conn.close()
    except Exception as e:
        print(f"[AUTO] Erro ao verificar partidas automáticas: {e}")

@app.before_request
def verificar_partidas_antes_do_request():
    auto_iniciar_partidas()

def inicializar_db():
    conn = obter_conexao_db()
    cursor = obter_cursor(conn)
    
    if os.environ.get('DATABASE_URL'):
        # Criando tabelas no PostgreSQL da Render (Usa SERIAL em vez de AUTOINCREMENT)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS usuarios (
                id SERIAL PRIMARY KEY,
                login TEXT UNIQUE NOT NULL,
                senha TEXT NOT NULL
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS palpites (
                id SERIAL PRIMARY KEY,
                usuario_id INTEGER,
                jogo_id TEXT NOT NULL,
                gols_time1 INTEGER,
                gols_time2 INTEGER,
                FOREIGN KEY (usuario_id) REFERENCES usuarios (id)
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS jogos (
                jogo_id TEXT PRIMARY KEY,
                time1 TEXT NOT NULL,
                time2 TEXT NOT NULL,
                gols_time1_real INTEGER,
                gols_time2_real INTEGER,
                status TEXT DEFAULT 'Pendente',
                etapa TEXT NOT NULL,
                data_hora TEXT NOT NULL,
                cidade TEXT
            )
        ''')
    else:
        # Criando tabelas no SQLite Local
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS usuarios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                login TEXT UNIQUE NOT NULL,
                senha TEXT NOT NULL
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS palpites (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                usuario_id INTEGER,
                jogo_id TEXT NOT NULL,
                gols_time1 INTEGER,
                gols_time2 INTEGER,
                FOREIGN KEY (usuario_id) REFERENCES usuarios (id)
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS jogos (
                jogo_id TEXT PRIMARY KEY,
                time1 TEXT NOT NULL,
                time2 TEXT NOT NULL,
                gols_time1_real INTEGER,
                gols_time2_real INTEGER,
                status TEXT DEFAULT 'Pendente',
                etapa TEXT NOT NULL,
                data_hora TEXT NOT NULL,
                cidade TEXT
            )
        ''')
    # Migrações DDL: cada ALTER TABLE usa SAVEPOINT próprio no PostgreSQL para evitar
    # que a falha de uma migração (coluna já existe) aborte a transação e impeça as demais.
    is_pg = os.environ.get('DATABASE_URL')

    def migrar_coluna(sql):
        if is_pg:
            cursor.execute("SAVEPOINT sp_migra")
        try:
            cursor.execute(sql)
        except Exception:
            if is_pg:
                cursor.execute("ROLLBACK TO SAVEPOINT sp_migra")
            # SQLite ignora erros via pass; a transação continua normalmente

    migrar_coluna("ALTER TABLE usuarios ADD COLUMN ativo INTEGER DEFAULT 1")
    migrar_coluna("ALTER TABLE jogos ADD COLUMN vencedor_penaltis TEXT")

    conn.commit()
    conn.close()

# 🚪 ROTA: Tela Inicial / Login
@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        login_user = request.form['usuario_login'].strip()
        senha_user = request.form['usuario_senha']
        
        conn = obter_conexao_db()
        cursor = obter_cursor(conn)
        
        query = preparar_query('SELECT * FROM usuarios WHERE login = ?')
        cursor.execute(query, (login_user,))
        usuario = cursor.fetchone()
        conn.close()
        
        if usuario and check_password_hash(usuario['senha'], senha_user):
            ativo = usuario['ativo'] if 'ativo' in usuario.keys() else 1
            if not ativo:
                flash('Conta inativa. Entre em contato com o administrador.')
            else:
                session['usuario_id'] = usuario['id']
                session['usuario_login'] = usuario['login']
                return redirect(url_for('palpites'))
        else:
            flash('Login ou senha incorretos!')
            
    return render_template('login.html')

# 📝 ROTA: Cadastro de Novo Usuário Seguro
@app.route('/cadastro', methods=['GET', 'POST'])
def cadastro():
    if request.method == 'POST':
        login_user = request.form['usuario_login'].strip()
        senha_user = request.form['usuario_senha'].strip()
        
        if not login_user or not senha_user:
            flash('Preencha todos os campos!')
            return render_template('cadastro.html')
            
        senha_criptografada = generate_password_hash(senha_user)
            
        conn = obter_conexao_db()
        cursor = obter_cursor(conn)
        try:
            query = preparar_query('INSERT INTO usuarios (login, senha) VALUES (?, ?)')
            cursor.execute(query, (login_user, senha_criptografada))
            conn.commit()
            conn.close()
            flash('Cadastro realizado com sucesso! Faça seu login.')
            return redirect(url_for('login'))
        except (sqlite3.IntegrityError, psycopg2.IntegrityError):
            conn.close()
            flash('Esse login já existe! Escolha outro.')
            
    return render_template('cadastro.html')

# 📋 ROTA: Ambiente do Usuário (Versão Blindada contra Erros de Carga)
@app.route('/palpites', methods=['GET', 'POST'])
def palpites():
    if 'usuario_id' not in session:
        return redirect(url_for('login'))
        
    usuario_id = session['usuario_id']
    conn = obter_conexao_db()
    cursor = obter_cursor(conn)

    # 💾 SE O USUÁRIO CLICOU EM SALVAR
    if request.method == 'POST':
        print("📥 Formulário recebido! Processando palpites...")
        for chave, valor in request.form.items():
            if chave.startswith('gols1_'):
                jogo_id = chave.replace('gols1_', '')
                gols_t1 = valor
                gols_t2 = request.form.get(f'gols2_{jogo_id}')

                if gols_t1 != '' and gols_t2 != '' and gols_t1 is not None and gols_t2 is not None:
                    try:
                        if int(gols_t1) < 0 or int(gols_t2) < 0:
                            print(f"⚠️ Tentativa de palpite negativo ignorada para o jogo {jogo_id}")
                            continue

                        query_check = preparar_query('SELECT 1 FROM palpites WHERE usuario_id = ? AND jogo_id = ?')
                        cursor.execute(query_check, (usuario_id, jogo_id))
                        existe = cursor.fetchone()

                        if existe:
                            query_up = preparar_query('''
                                UPDATE palpites 
                                SET gols_time1 = ?, gols_time2 = ? 
                                WHERE usuario_id = ? AND jogo_id = ?
                            ''')
                            cursor.execute(query_up, (int(gols_t1), int(gols_t2), usuario_id, jogo_id))
                        else:
                            query_in = preparar_query('''
                                INSERT INTO palpites (usuario_id, jogo_id, gols_time1, gols_time2) 
                                VALUES (?, ?, ?, ?)
                            ''')
                            cursor.execute(query_in, (usuario_id, jogo_id, int(gols_t1), int(gols_t2)))
                    except Exception as e:
                        print(f"❌ Erro ao inserir/atualizar jogo {jogo_id}: {e}")
        
        conn.commit()
        conn.close()
        print("💾 Todos os palpites foram validados e commitados no banco!")
        flash('Palpites salvos com sucesso!')
        return redirect(url_for('palpites'))

    # 🔍 BUSCA DOS JOGOS
    tipo_cursor = type(cursor).__name__.lower()
    placeholder = '%s' if 'psycopg2' in tipo_cursor or 'cursor' in tipo_cursor else '?'
    
    # Usa preparar_query para adaptar placeholders do SQLite (?) para PostgreSQL (%s).
    query_select = preparar_query("""
        SELECT
            j.jogo_id, j.time1, j.time2, j.etapa, j.data_hora, j.cidade, j.status,
            j.flag_code_time1, j.flag_code_time2,
            j.gols_time1_real, j.gols_time2_real,
            p.gols_time1 AS gols_time1_palpite,
            p.gols_time2 AS gols_time2_palpite
        FROM jogos j
        LEFT JOIN palpites p
            ON j.jogo_id = p.jogo_id
            AND p.usuario_id = ?
        ORDER BY
            CASE WHEN j.etapa LIKE 'Fase de Grupos%' THEN j.etapa ELSE 'Mata-Mata' END ASC,
            CASE WHEN j.etapa LIKE 'Fase de Grupos%' THEN j.data_hora ELSE '' END ASC,
            CAST(SUBSTR(j.jogo_id, 6) AS INTEGER) ASC
    """)

    cursor.execute(query_select, (usuario_id,))
    jogos = cursor.fetchall()
    
    etapas_ordem = [
        "Fase de Grupos Rodada 1", "Fase de Grupos Rodada 2", "Fase de Grupos Rodada 3",
        "Dezesseis-avos de final", "Oitavas de final", "Quartas de final", "Semifinais",
        "Disputa de terceiro lugar", "Final"
    ]
    
    jogos_agrupados = {etapa: [] for etapa in etapas_ordem}
    
    for row in jogos:
        jogo = dict(row)
        etapa_jogo = jogo['etapa']
        
        jogo['acertou_placar'] = False
        jogo['acertou_vencedor'] = False
        jogo['bonus_saldo'] = False
        jogo['bonus_gols'] = False
        jogo['pontos_faturados'] = 0
        
        if jogo['status'] == 'Encerrado' and jogo['gols_time1_real'] is not None and jogo['gols_time1_palpite'] is not None:
            try:
                g1_real = int(jogo['gols_time1_real'])
                g2_real = int(jogo['gols_time2_real'])
                g1_palp = int(jogo['gols_time1_palpite'])
                g2_palp = int(jogo['gols_time2_palpite'])

                pontos_base = 0
                if g1_real == g1_palp and g2_real == g2_palp:
                    jogo['acertou_placar'] = True
                    pontos_base = 10
                else:
                    venc_real = "t1" if g1_real > g2_real else "t2" if g2_real > g1_real else "empate"
                    venc_palp = "t1" if g1_palp > g2_palp else "t2" if g2_palp > g1_palp else "empate"

                    if venc_real == venc_palp:
                        jogo['acertou_vencedor'] = True
                        pontos_base += 5
                        if (g1_real - g2_real) == (g1_palp - g2_palp):
                            jogo['bonus_saldo'] = True
                            pontos_base += 2

                    if g1_real == g1_palp or g2_real == g2_palp:
                        jogo['bonus_gols'] = True
                        pontos_base += 1

                jogo['pontos_faturados'] = pontos_base * multiplicador_da_fase(jogo['etapa'])
            except (ValueError, TypeError):
                pass

        if etapa_jogo not in jogos_agrupados:
            jogos_agrupados[etapa_jogo] = []
        jogos_agrupados[etapa_jogo].append(jogo)

    conn.close()
    return render_template('palpites.html', jogos_agrupados=jogos_agrupados)

# 🏆 ROTA: Ranking Geral
@app.route('/ranking')
def ranking():
    if 'usuario_id' not in session:
        return redirect(url_for('login'))
        
    conn = obter_conexao_db()
    cursor = obter_cursor(conn)
    
    cursor.execute('SELECT id, login FROM usuarios')
    usuarios = cursor.fetchall()
    
    query_jogos = preparar_query('SELECT * FROM jogos WHERE status = ?')
    cursor.execute(query_jogos, ("Encerrado",))
    jogos_encerrados = cursor.fetchall()
    
    cursor.execute('SELECT * FROM palpites')
    todos_palpites = cursor.fetchall()
    conn.close()
    
    tabela_pontos = {u['id']: {'id': u['id'], 'login': u['login'], 'pontos': 0} for u in usuarios}
    mapa_jogos = {j['jogo_id']: j for j in jogos_encerrados}
    
    for p in todos_palpites:
        jogo_id = p['jogo_id']
        usr_id = p['usuario_id']

        if jogo_id in mapa_jogos and usr_id in tabela_pontos:
            jogo = mapa_jogos[jogo_id]

            if jogo['gols_time1_real'] is None or jogo['gols_time2_real'] is None:
                continue

            try:
                g1_real = int(jogo['gols_time1_real'])
                g2_real = int(jogo['gols_time2_real'])
                g1_palp = int(p['gols_time1'])
                g2_palp = int(p['gols_time2'])
            except (ValueError, TypeError):
                continue

            mult = multiplicador_da_fase(jogo['etapa'])
            tabela_pontos[usr_id]['pontos'] += calcular_pontos(g1_real, g2_real, g1_palp, g2_palp) * mult

    ranking_ordenado = list(tabela_pontos.values())
    ranking_ordenado.sort(key=lambda x: x['pontos'], reverse=True)
    
    print(f"📊 DADOS ENVIADOS PARA O HTML: {ranking_ordenado}")
    
    return render_template('ranking.html', usuarios_ranking=ranking_ordenado)

#ROTA: Admin (Iniciar/Encerrar Jogos e Lançar Resultados) - Versão Blindada com Diagnóstico Detalhado

@app.route('/admin', methods=['GET', 'POST'])
def admin():
    if 'usuario_id' not in session:
        return redirect(url_for('login'))
        
    if session['usuario_login'] != 'Lucas':
        flash('Acesso negado! Esta área é exclusiva para o administrador.')
        return redirect(url_for('palpites'))

    conn = obter_conexao_db()
    cursor = obter_cursor(conn)
    
    if request.method == 'POST':
        jogo_id = request.form.get('jogo_id')
        acao = request.form.get('acao')
        
        print(f"\n=== 📥 COMANDO ADMIN RECEBIDO ===")
        print(f"Jogo ID: {jogo_id} | Ação clicada: {acao}")
        
        if acao == 'iniciar':
            query_init = preparar_query("UPDATE jogos SET status = 'Em Andamento' WHERE jogo_id = ?")
            cursor.execute(query_init, (jogo_id,))
            print(f"🏃 Partida {jogo_id} alterada para 'Em Andamento'.")
            flash('Partida iniciada! Palpites trancados.')
            
        elif acao == 'encerrar':
            gols_t1 = request.form.get('gols_time1_real')
            gols_t2 = request.form.get('gols_time2_real')
            vencedor_penaltis = request.form.get('vencedor_penaltis', '').strip() or None

            print(f"⚽ Placar digitado: {gols_t1} X {gols_t2} | Pênaltis: {vencedor_penaltis}")

            FASES_ELIMINATORIAS = {
                'Dezesseis-avos de final', 'Oitavas de final',
                'Quartas de final', 'Semifinais', 'Final'
            }

            if gols_t1 is not None and gols_t2 is not None and gols_t1.strip() != '' and gols_t2.strip() != '':
                # Busca etapa e times do jogo para validar pênaltis
                q_jogo = preparar_query("SELECT etapa, time1, time2 FROM jogos WHERE jogo_id = ?")
                cursor.execute(q_jogo, (jogo_id,))
                row = cursor.fetchone()
                etapa_jogo = (row['etapa'] if isinstance(row, dict) else row[0]) if row else ''
                time1_jogo = (row['time1'] if isinstance(row, dict) else row[1]) if row else ''
                time2_jogo = (row['time2'] if isinstance(row, dict) else row[2]) if row else ''

                eh_eliminatorio = etapa_jogo in FASES_ELIMINATORIAS
                eh_empate = int(gols_t1) == int(gols_t2)

                if eh_eliminatorio and eh_empate and not vencedor_penaltis:
                    flash('Erro: Jogo eliminatório empatado precisa de um vencedor nos pênaltis!')
                elif eh_eliminatorio and eh_empate and vencedor_penaltis not in (time1_jogo, time2_jogo):
                    flash(f'Erro: Vencedor nos pênaltis deve ser {time1_jogo} ou {time2_jogo}!')
                else:
                    vp_salvar = vencedor_penaltis if (eh_eliminatorio and eh_empate) else None
                    query_end = preparar_query('''
                        UPDATE jogos
                        SET gols_time1_real = ?, gols_time2_real = ?, vencedor_penaltis = ?, status = 'Encerrado'
                        WHERE jogo_id = ?
                    ''')
                    cursor.execute(query_end, (int(gols_t1), int(gols_t2), vp_salvar, jogo_id))
                    conn.commit()
                    is_pg = eh_postgres(conn)
                    print(f"✅ Jogo {jogo_id} ENCERRADO no banco {'Render/PostgreSQL' if is_pg else 'local/SQLite'}.")
                    flash('Resultado gravado e jogo encerrado com sucesso!')

                    # 🛠️ O DETETIVE ENTRA EXATAMENTE AQUI:
                    try:
                        print("\n🔍 [DIAGNÓSTICO] Quais tabelas existem nesta conexão?")
                        if is_pg:
                            cursor.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' ORDER BY table_name")
                        else:
                            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
                        tabelas = cursor.fetchall()

                        # Tenta ler formato dicionário ou tupla pura do SQLite
                        nomes_tabelas = []
                        for t in tabelas:
                            if isinstance(t, dict): nomes_tabelas.append(t['name'])
                            elif hasattr(t, 'keys') and 'name' in t.keys(): nomes_tabelas.append(t['name'])
                            elif hasattr(t, 'keys') and 'table_name' in t.keys(): nomes_tabelas.append(t['table_name'])
                            else: nomes_tabelas.append(t[0])

                        print(f"📋 Tabelas encontradas no banco: {nomes_tabelas}")

                        print("🏆 Disparando recálculo automático da árvore de mata-mata...")
                        atualizar_chaveamento_completo(cursor, is_postgres=is_pg)
                        conn.commit()
                        print("✅ Árvore de mata-mata atualizada com sucesso no lote atual!")
                    except Exception as e:
                        conn.rollback()
                        print(f"❌ Erro crítico ao atualizar o chaveamento: {e}")
            else:
                flash('Erro: Você precisa digitar os gols antes de encerrar!')
                
        elif acao == 'reabrir':
            # Volta a partida para Pendente sem apagar palpites existentes.
            # O fechamento automático voltará a agir normalmente quando o horário real chegar.
            query_reabrir = preparar_query("UPDATE jogos SET status = 'Pendente' WHERE jogo_id = ?")
            cursor.execute(query_reabrir, (jogo_id,))
            print(f"🔓 Partida {jogo_id} reaberta para palpites pelo admin.")
            flash('Partida reaberta! Palpites liberados novamente.')

        # 💾 O commit agora salva o placar DO JOGO + O CHAVEAMENTO recalculado juntos!
        conn.commit()
        conn.close()
        print("=== 💾 ALTERAÇÕES SALVAS COM COMMIT ===\n")
        return redirect(url_for('admin'))
        
    # 🔍 BUSCA E ORDENAÇÃO INTELIGENTE (Fase de Grupos por Data | Mata-Mata por ID)
    cursor.execute('''
        SELECT * FROM jogos 
        ORDER BY 
            CASE WHEN etapa LIKE 'Fase de Grupos%' THEN etapa ELSE 'Mata-Mata' END ASC,
            CASE WHEN etapa LIKE 'Fase de Grupos%' THEN data_hora ELSE '' END ASC,
            CAST(SUBSTR(jogo_id, 6) AS INTEGER) ASC
    ''')
    jogos = cursor.fetchall()
    conn.close()
    
    etapas_ordem = [
        "Fase de Grupos Rodada 1", "Fase de Grupos Rodada 2", "Fase de Grupos Rodada 3",
        "Dezesseis-avos de final", "Oitavas de final", "Quartas de final", "Semifinais",
        "Disputa de terceiro lugar", "Final"
    ]
    
    jogos_agrupados = {etapa: [] for etapa in etapas_ordem}
    
    for jogo in jogos:
        etapa_jogo = jogo['etapa']
        if etapa_jogo not in jogos_agrupados:
            jogos_agrupados[etapa_jogo] = []
        jogos_agrupados[etapa_jogo].append(jogo)
        
    return render_template('admin.html', jogos_agrupados=jogos_agrupados)

# 👥 ROTA: Gerenciamento de Usuários (Admin)
@app.route('/admin/usuarios', methods=['GET', 'POST'])
def admin_usuarios():
    if 'usuario_id' not in session or session.get('usuario_login') != 'Lucas':
        flash('Acesso negado!')
        return redirect(url_for('login'))

    conn = obter_conexao_db()
    cursor = obter_cursor(conn)

    if request.method == 'POST':
        acao = request.form.get('acao')
        usuario_id = request.form.get('usuario_id')

        if acao == 'excluir':
            q_del_palpites = preparar_query("DELETE FROM palpites WHERE usuario_id = ?")
            cursor.execute(q_del_palpites, (usuario_id,))
            q_del_user = preparar_query("DELETE FROM usuarios WHERE id = ?")
            cursor.execute(q_del_user, (usuario_id,))
            conn.commit()
            flash('Usuário excluído com sucesso.')

        elif acao == 'inativar':
            q = preparar_query("UPDATE usuarios SET ativo = 0 WHERE id = ?")
            cursor.execute(q, (usuario_id,))
            conn.commit()
            flash('Usuário inativado. Ele não conseguirá mais fazer login.')

        elif acao == 'ativar':
            q = preparar_query("UPDATE usuarios SET ativo = 1 WHERE id = ?")
            cursor.execute(q, (usuario_id,))
            conn.commit()
            flash('Usuário reativado com sucesso.')

        elif acao == 'redefinir_senha':
            nova_senha = request.form.get('nova_senha', '').strip()
            if not nova_senha:
                flash('Informe a nova senha.')
            else:
                nova_hash = generate_password_hash(nova_senha)
                q = preparar_query("UPDATE usuarios SET senha = ? WHERE id = ?")
                cursor.execute(q, (nova_hash, usuario_id))
                conn.commit()
                flash('Senha redefinida com sucesso.')

        conn.close()
        return redirect(url_for('admin_usuarios'))

    cursor.execute("SELECT id, login, COALESCE(ativo, 1) as ativo FROM usuarios ORDER BY login ASC")
    usuarios = cursor.fetchall()

    # Conta palpites por usuário para exibição
    contagem_palpites = {}
    for u in usuarios:
        q = preparar_query("SELECT COUNT(*) as total FROM palpites WHERE usuario_id = ?")
        cursor.execute(q, (u['id'],))
        row = cursor.fetchone()
        contagem_palpites[u['id']] = row['total'] if row else 0

    conn.close()
    return render_template('admin_usuarios.html', usuarios=usuarios, contagem_palpites=contagem_palpites)

#ROTA: Visualizar Palpites de um Amigo (Ajustada para o seu HTML original)

# 📊 ROTA: Comparativo de Palpites (Tabela cruzada jogos × jogadores)
@app.route('/comparativo')
def comparativo():
    if 'usuario_id' not in session:
        return redirect(url_for('login'))

    conn = obter_conexao_db()
    cursor = obter_cursor(conn)

    cursor.execute("SELECT id, login FROM usuarios ORDER BY login ASC")
    usuarios = [dict(u) for u in cursor.fetchall()]

    query_jogos = preparar_query(
        "SELECT * FROM jogos WHERE status != 'Pendente' ORDER BY data_hora ASC"
    )
    cursor.execute(query_jogos)
    jogos_raw = cursor.fetchall()

    cursor.execute("SELECT * FROM palpites")
    todos_palpites = cursor.fetchall()
    conn.close()

    # {usuario_id: {jogo_id: (g1, g2)}}
    mapa_palpites = {}
    for p in todos_palpites:
        uid = p['usuario_id']
        jid = p['jogo_id']
        if uid not in mapa_palpites:
            mapa_palpites[uid] = {}
        mapa_palpites[uid][jid] = (p['gols_time1'], p['gols_time2'])

    def _pts(g1r, g2r, g1p, g2p):
        if g1r == g1p and g2r == g2p:
            return 10
        pts = 0
        vr = "t1" if g1r > g2r else "t2" if g2r > g1r else "e"
        vp = "t1" if g1p > g2p else "t2" if g2p > g1p else "e"
        if vr == vp:
            pts += 5
            if (g1r - g2r) == (g1p - g2p):
                pts += 2
        if g1r == g1p or g2r == g2p:
            pts += 1
        return pts

    pontos_totais = {u['id']: 0 for u in usuarios}

    etapas_ordem = [
        "Fase de Grupos Rodada 1", "Fase de Grupos Rodada 2", "Fase de Grupos Rodada 3",
        "Dezesseis-avos de final", "Oitavas de final", "Quartas de final",
        "Semifinais", "Disputa de terceiro lugar", "Final"
    ]
    jogos_agrupados = {e: [] for e in etapas_ordem}

    for row in jogos_raw:
        jogo = dict(row)
        jid = jogo['jogo_id']
        encerrado = jogo['status'] == 'Encerrado' and jogo.get('gols_time1_real') is not None

        palpites_jogo = {}
        for u in usuarios:
            uid = u['id']
            palpite = mapa_palpites.get(uid, {}).get(jid)
            if palpite is None:
                palpites_jogo[uid] = None
                continue
            g1p, g2p = palpite
            pontos = None
            acerto = None
            if encerrado:
                try:
                    pts_base = _pts(
                        int(jogo['gols_time1_real']), int(jogo['gols_time2_real']),
                        int(g1p), int(g2p)
                    )
                    mult = multiplicador_da_fase(jogo['etapa'])
                    pontos = pts_base * mult
                    acerto = 'exato' if pts_base == 10 else ('vencedor' if pts_base >= 5 else 'errou')
                    pontos_totais[uid] += pontos
                except (ValueError, TypeError):
                    pass
            palpites_jogo[uid] = {'g1': g1p, 'g2': g2p, 'pontos': pontos, 'acerto': acerto}

        jogo['palpites'] = palpites_jogo
        etapa = jogo['etapa']
        if etapa not in jogos_agrupados:
            jogos_agrupados[etapa] = []
        jogos_agrupados[etapa].append(jogo)

    # Ordena usuários por pontuação total (ranking)
    usuarios.sort(key=lambda u: pontos_totais[u['id']], reverse=True)
    for u in usuarios:
        u['pontos_total'] = pontos_totais[u['id']]

    # Totais por etapa: {etapa: {uid: pts}}
    totais_etapa = {}
    for etapa, lista in jogos_agrupados.items():
        totais_etapa[etapa] = {u['id']: 0 for u in usuarios}
        for jogo in lista:
            for uid, p in jogo['palpites'].items():
                if p and p['pontos']:
                    totais_etapa[etapa][uid] += p['pontos']

    return render_template(
        'comparativo.html',
        usuarios=usuarios,
        jogos_agrupados=jogos_agrupados,
        etapas_ordem=etapas_ordem,
        totais_etapa=totais_etapa,
        usuario_logado_id=session['usuario_id']
    )

# 🔑 ROTA: Alterar Senha
@app.route('/alterar-senha', methods=['GET', 'POST'])
def alterar_senha():
    if 'usuario_id' not in session:
        return redirect(url_for('login'))
        
    if request.method == 'POST':
        senha_atual = request.form.get('senha_atual', '').strip()
        nova_senha = request.form.get('nova_senha', '').strip()
        confirmar_senha = request.form.get('confirmar_senha', '').strip()
        usuario_id = session['usuario_id']
        
        if not senha_atual or not nova_senha or not confirmar_senha:
            flash('⚠️ Todos os campos são obrigatórios!', 'erro')
            return redirect(url_for('alterar_senha'))
            
        if nova_senha != confirmar_senha:
            flash('⚠️ A nova senha e a confirmação não batem!', 'erro')
            return redirect(url_for('alterar_senha'))
            
        conn = obter_conexao_db()
        cursor = obter_cursor(conn)
        
        query_usr = preparar_query('SELECT senha FROM usuarios WHERE id = ?')
        cursor.execute(query_usr, (usuario_id,))
        usuario = cursor.fetchone()
        
        if usuario and check_password_hash(usuario['senha'], senha_atual):
            nova_senha_criptografada = generate_password_hash(nova_senha)
            
            query_up = preparar_query('UPDATE usuarios SET senha = ? WHERE id = ?')
            cursor.execute(query_up, (nova_senha_criptografada, usuario_id))
            conn.commit()
            conn.close()
            
            flash('✅ Senha alterada com sucesso!', 'sucesso')
            return redirect(url_for('palpites'))
        else:
            conn.close()
            flash('❌ Senha atual incorreta!', 'erro')
            return redirect(url_for('alterar_senha'))
            
    return render_template('alterar_senha.html')

@app.route('/api/evolucao-pontos')
def evolucao_pontos():
    if 'usuario_id' not in session:
        return jsonify({'erro': 'Não autorizado'}), 401
        
    try:
        usuario_logado_id = int(session['usuario_id'])
    except (ValueError, TypeError):
        usuario_logado_id = session['usuario_id']
        
    conn = obter_conexao_db()
    cursor = conn.cursor()
    
    is_postgres = 'sqlite' not in str(type(conn)).lower()
    placeholder = '%s' if is_postgres else '?'
    
    # 📑 FUNÇÃO INTERNA COM A SUA REGRA OFICIAL DE PONTOS
    def calcular_pontos_oficial(g1_real, g2_real, g1_palpite, g2_palpite):
        # 1. Verificação de acerto em cheio (Placar Exato)
        if g1_real == g1_palpite and g2_real == g2_palpite:
            return 10  # Acerto completo não acumula com os outros bônus

        pontos = 0
        # 2. Verificação do Vencedor / Empate (5 pontos)
        vencedor_real = "time1" if g1_real > g2_real else "time2" if g2_real > g1_real else "empate"
        vencedor_palpite = "time1" if g1_palpite > g2_palpite else "time2" if g2_palpite > g1_palpite else "empate"
        
        if vencedor_real == vencedor_palpite:
            pontos += 5
            
            # 3. Bônus de Saldo de Gols (2 pontos)
            saldo_real = g1_real - g2_real
            saldo_palpite = g1_palpite - g2_palpite
            if saldo_real == saldo_palpite:
                pontos += 2

        # 4. Bônus de Gols de um dos times (1 ponto)
        if g1_real == g1_palpite or g2_real == g2_palpite:
            pontos += 1
            
        return pontos

    # 1. 🏆 BUSCA DOS USUÁRIOS
    cursor.execute('SELECT id, login FROM usuarios')
    todos_usuarios_bruto = cursor.fetchall()

    # 2. 🔎 IDENTIFICAÇÃO DO TOP 3 REAL USANDO A SUA REGRA
    cursor.execute('''
        SELECT u.id, j.gols_time1_real, j.gols_time2_real, p.gols_time1, p.gols_time2, j.etapa
        FROM usuarios u
        JOIN palpites p ON u.id = p.usuario_id
        JOIN jogos j ON p.jogo_id = j.jogo_id
        WHERE j.status = 'Encerrado'
    ''')
    todos_palpites_ranking = cursor.fetchall()

    pontos_dict = {int(user[0]): 0 for user in todos_usuarios_bruto}
    for u_id_bruto, g1_r, g2_r, g1_p, g2_p, etapa in todos_palpites_ranking:
        u_id = int(u_id_bruto)
        try:
            g1_r, g2_r, g1_p, g2_p = int(g1_r), int(g2_r), int(g1_p), int(g2_p)
        except (ValueError, TypeError):
            continue
        pontos_dict[u_id] += calcular_pontos_oficial(g1_r, g2_r, g1_p, g2_p) * multiplicador_da_fase(etapa)

    lista_usuarios = []
    for user_bruto in todos_usuarios_bruto:
        u_id = int(user_bruto[0])
        lista_usuarios.append({
            'id': u_id,
            'login': user_bruto[1],
            'pontos': pontos_dict.get(u_id, 0)
        })
        
    lista_usuarios.sort(key=lambda x: (-x['pontos'], x['login']))
    top3_usuarios = [(user['id'], user['login']) for user in lista_usuarios[:3]]

    # 3. 🔐 MONTAGEM DOS ALVOS DO GRÁFICO
    usuarios_alvo = {}
    for u_id, u_login in top3_usuarios:
        usuarios_alvo[int(u_id)] = f"🏆 {u_login}"
        
    if usuario_logado_id not in usuarios_alvo:
        cursor.execute('SELECT login FROM usuarios WHERE id = ' + placeholder, (usuario_logado_id,))
        res_logado = cursor.fetchone()
        login_logado = res_logado[0] if res_logado else "Você"
        usuarios_alvo[usuario_logado_id] = f"👤 {login_logado} (Você)"
    else:
        if not usuarios_alvo[usuario_logado_id].endswith("(Você)"):
            usuarios_alvo[usuario_logado_id] += " (Você)"

    # 4. 🔎 BUSCA DETALHADA DOS PALPITES DOS ALVOS
    ids_busca = list(usuarios_alvo.keys())
    placeholders_in = ','.join(['%s' if is_postgres else '?' for _ in ids_busca])
    
    query_palpites = f'''
        SELECT p.usuario_id, j.jogo_id, j.gols_time1_real, j.gols_time2_real, p.gols_time1, p.gols_time2, j.etapa
        FROM palpites p
        INNER JOIN jogos j ON p.jogo_id = j.jogo_id
        WHERE p.usuario_id IN ({placeholders_in}) AND j.status = 'Encerrado'
    '''
    cursor.execute(query_palpites, tuple(ids_busca))
    todos_palpites = cursor.fetchall()

    cursor.execute("SELECT jogo_id FROM jogos WHERE status = 'Encerrado'")
    jogos_encerrados_bruto = cursor.fetchall()
    conn.close()

    lista_jogos = [j[0] for j in jogos_encerrados_bruto]
    try:
        lista_jogos.sort(key=lambda x: int(x.split('_')[1]))
    except Exception:
        lista_jogos.sort()

    palpites_estruturados = {u_id: {} for u_id in ids_busca}
    for u_id_bruto, jogo_id, g1_r, g2_r, g1_p, g2_p, etapa in todos_palpites:
        u_id = int(u_id_bruto)
        if u_id in palpites_estruturados:
            palpites_estruturados[u_id][jogo_id] = (g1_r, g2_r, g1_p, g2_p, etapa)

    # 5. 📉 LOOP DE CONSTRUÇÃO DAS LINHAS
    linhas_grafico = []
    cores = ['#d97706', '#9ca3af', '#b45309', '#2b7a78']

    for index, u_id in enumerate(ids_busca):
        pontos_acumulados = 0
        pontos_eixo_y = []

        for jogo_id in lista_jogos:
            if jogo_id in palpites_estruturados[u_id]:
                try:
                    g1_real, g2_real, g1_palpite, g2_palpite, etapa = palpites_estruturados[u_id][jogo_id]
                    g1_real, g2_real, g1_palpite, g2_palpite = int(g1_real), int(g2_real), int(g1_palpite), int(g2_palpite)
                except (ValueError, TypeError):
                    pontos_eixo_y.append(pontos_acumulados)
                    continue

                pontos_da_partida = calcular_pontos_oficial(g1_real, g2_real, g1_palpite, g2_palpite) * multiplicador_da_fase(etapa)
                pontos_acumulados += pontos_da_partida
            
            pontos_eixo_y.append(pontos_acumulados)
            
        cor_linha = '#2b7a78' if u_id == usuario_logado_id else cores[min(index, 2)]
        
        linhas_grafico.append({
            'label': usuarios_alvo[u_id],
            'dados': pontos_eixo_y,
            'cor': cor_linha
        })
        
    eixo_x_formatado = [f"Jogo {j.split('_')[1]}" if '_' in j else j for j in lista_jogos]
    
    return jsonify({
        'partidas': eixo_x_formatado,
        'linhas': linhas_grafico
    })

# ROTA: Evolução Completa de Pontos (Todos os Usuários, Gráfico Detalhado)
@app.route('/api/evolucao-pontos-completo')
def evolucao_pontos_completo():
    if 'usuario_id' not in session:
        return jsonify({'erro': 'Não autorizado'}), 401
        
    conn = obter_conexao_db()
    cursor = conn.cursor()
    
    # Reaproveitamos a sua função interna idêntica de pontos
    def calcular_pontos_oficial(g1_real, g2_real, g1_palpite, g2_palpite):
        if g1_real == g1_palpite and g2_real == g2_palpite:
            return 10
        pontos = 0
        vencedor_real = "time1" if g1_real > g2_real else "time2" if g2_real > g1_real else "empate"
        vencedor_palpite = "time1" if g1_palpite > g2_palpite else "time2" if g2_palpite > g1_palpite else "empate"
        if vencedor_real == vencedor_palpite:
            pontos += 5
            saldo_real = g1_real - g2_real
            saldo_palpite = g1_palpite - g2_palpite
            if saldo_real == saldo_palpite:
                pontos += 2
        if g1_real == g1_palpite or g2_real == g2_palpite:
            pontos += 1
        return pontos

    cursor.execute('SELECT id, login FROM usuarios')
    todos_usuarios = cursor.fetchall()

    cursor.execute('''
        SELECT p.usuario_id, j.jogo_id, j.gols_time1_real, j.gols_time2_real, p.gols_time1, p.gols_time2, j.etapa
        FROM palpites p
        INNER JOIN jogos j ON p.jogo_id = j.jogo_id
        WHERE j.status = 'Encerrado'
    ''')
    todos_palpites = cursor.fetchall()

    cursor.execute("SELECT jogo_id FROM jogos WHERE status = 'Encerrado'")
    jogos_encerrados_bruto = cursor.fetchall()
    conn.close()

    lista_jogos = [j[0] for j in jogos_encerrados_bruto]
    try:
        lista_jogos.sort(key=lambda x: int(x.split('_')[1]))
    except Exception:
        lista_jogos.sort()

    palpites_estruturados = {int(u[0]): {} for u in todos_usuarios}
    for u_id_bruto, jogo_id, g1_r, g2_r, g1_p, g2_p, etapa in todos_palpites:
        u_id = int(u_id_bruto)
        if u_id in palpites_estruturados:
            palpites_estruturados[u_id][jogo_id] = (g1_r, g2_r, g1_p, g2_p, etapa)

    # Lista de cores dinâmicas para o gráfico não repetir cores iguais lado a lado
    paleta_cores = [
        '#2b7a78', '#d97706', '#3b82f6', '#10b981', '#ef4444', '#8b5cf6',
        '#ec4899', '#f59e0b', '#6366f1', '#14b8a6', '#a855f7', '#06b6d4'
    ]

    linhas_grafico = []
    for index, (u_id_bruto, login) in enumerate(todos_usuarios):
        u_id = int(u_id_bruto)
        pontos_acumulados = 0
        pontos_eixo_y = []

        for jogo_id in lista_jogos:
            if jogo_id in palpites_estruturados[u_id]:
                try:
                    g1_real, g2_real, g1_palpite, g2_palpite, etapa = palpites_estruturados[u_id][jogo_id]
                    g1_real, g2_real, g1_palpite, g2_palpite = int(g1_real), int(g2_real), int(g1_palpite), int(g2_palpite)
                except (ValueError, TypeError):
                    pontos_eixo_y.append(pontos_acumulados)
                    continue

                pontos_acumulados += calcular_pontos_oficial(g1_real, g2_real, g1_palpite, g2_palpite) * multiplicador_da_fase(etapa)
            
            pontos_eixo_y.append(pontos_acumulados)
            
        cor_linha = paleta_cores[index % len(paleta_cores)]
        
        linhas_grafico.append({
            'label': login,
            'dados': pontos_eixo_y,
            'cor': cor_linha
        })
        
    eixo_x_formatado = [f"Jogo {j.split('_')[1]}" if '_' in j else j for j in lista_jogos]
    
    return jsonify({
        'partidas': eixo_x_formatado,
        'linhas': linhas_grafico
    })

# 🎯 ROTA: Dashboard de Desempenho (página)
@app.route('/dashboard')
def dashboard():
    if 'usuario_id' not in session:
        return redirect(url_for('login'))
    return render_template('dashboard.html')


# 🎯 ROTA: API do Dashboard
@app.route('/api/dashboard')
def api_dashboard():
    if 'usuario_id' not in session:
        return jsonify({'erro': 'Não autorizado'}), 401

    try:
        uid_logado = int(session['usuario_id'])
    except (ValueError, TypeError):
        uid_logado = session['usuario_id']

    conn  = obter_conexao_db()
    cursor = obter_cursor(conn)

    cursor.execute("SELECT id, login FROM usuarios ORDER BY login ASC")
    usuarios = [dict(u) for u in cursor.fetchall()]

    q_jogos = preparar_query(
        "SELECT * FROM jogos WHERE status = 'Encerrado' AND gols_time1_real IS NOT NULL "
        "ORDER BY data_hora ASC"
    )
    cursor.execute(q_jogos)
    jogos = [dict(j) for j in cursor.fetchall()]

    cursor.execute("SELECT * FROM palpites")
    todos_palpites = cursor.fetchall()
    conn.close()

    # Mapa de palpites: {uid: {jogo_id: (g1, g2)}}
    mapa = {}
    for p in todos_palpites:
        uid  = p['usuario_id']
        jid  = p['jogo_id']
        if uid not in mapa:
            mapa[uid] = {}
        mapa[uid][jid] = (p['gols_time1'], p['gols_time2'])

    def _pts_tipo(g1r, g2r, g1p, g2p):
        """Retorna (pontos, tipo) onde tipo é 'exato'|'vencedor'|'errou'."""
        g1r, g2r, g1p, g2p = int(g1r), int(g2r), int(g1p), int(g2p)
        if g1r == g1p and g2r == g2p:
            return 10, 'exato'
        pts = 0
        vr = 't1' if g1r > g2r else 't2' if g2r > g1r else 'e'
        vp = 't1' if g1p > g2p else 't2' if g2p > g1p else 'e'
        if vr == vp:
            pts += 5
            if (g1r - g2r) == (g1p - g2p):
                pts += 2
        if g1r == g1p or g2r == g2p:
            pts += 1
        return pts, ('vencedor' if pts >= 5 else 'errou')

    # ── Média do grupo por jogo ────────────────────────────────────────────────
    media_grupo = {}  # jogo_id -> float
    for j in jogos:
        jid  = j['jogo_id']
        soma = 0
        cnt  = 0
        for u in usuarios:
            pal = mapa.get(u['id'], {}).get(jid)
            if pal:
                try:
                    pts, _ = _pts_tipo(j['gols_time1_real'], j['gols_time2_real'], pal[0], pal[1])
                    soma += pts
                    cnt  += 1
                except (ValueError, TypeError):
                    pass
        media_grupo[jid] = round(soma / cnt, 1) if cnt else 0

    # ── INDIVIDUAL ─────────────────────────────────────────────────────────────
    etapas_ordem = [
        "Fase de Grupos Rodada 1", "Fase de Grupos Rodada 2", "Fase de Grupos Rodada 3",
        "Dezesseis-avos de final", "Oitavas de final", "Quartas de final",
        "Semifinais", "Disputa de terceiro lugar", "Final"
    ]
    etapa_abrev = {
        "Fase de Grupos Rodada 1": "FG R1", "Fase de Grupos Rodada 2": "FG R2",
        "Fase de Grupos Rodada 3": "FG R3", "Dezesseis-avos de final": "16-avos",
        "Oitavas de final": "Oitavas", "Quartas de final": "Quartas",
        "Semifinais": "Semi", "Disputa de terceiro lugar": "3° Lugar", "Final": "Final"
    }

    taxa = {'exato': 0, 'vencedor': 0, 'errou': 0, 'sem_palpite': 0}
    por_fase = {e: {'exato': 0, 'vencedor': 0, 'errou': 0, 'pts': 0, 'total': 0}
                for e in etapas_ordem}
    pts_por_jogo  = []   # para o gráfico de linha
    dist_pontos   = {0: 0, 1: 0, 5: 0, 6: 0, 7: 0, 8: 0, 10: 0}
    historico_streak = []  # cronológico (mais antigo primeiro)

    for j in jogos:
        jid   = j['jogo_id']
        etapa = j['etapa']
        label = f"{j['time1']} x {j['time2']}"
        pal   = mapa.get(uid_logado, {}).get(jid)

        if pal is None:
            taxa['sem_palpite'] += 1
            pts_por_jogo.append({'label': label, 'pts': None,
                                 'media': media_grupo[jid], 'etapa': etapa})
            historico_streak.append('sem_palpite')
            continue
        try:
            pts, tipo = _pts_tipo(j['gols_time1_real'], j['gols_time2_real'], pal[0], pal[1])
        except (ValueError, TypeError):
            taxa['sem_palpite'] += 1
            pts_por_jogo.append({'label': label, 'pts': None,
                                 'media': media_grupo[jid], 'etapa': etapa})
            historico_streak.append('sem_palpite')
            continue

        taxa[tipo] += 1
        pts_por_jogo.append({'label': label, 'pts': pts,
                             'media': media_grupo[jid], 'etapa': etapa})
        historico_streak.append('acerto' if pts >= 5 else 'erro')

        ef = por_fase.get(etapa) or por_fase.setdefault(etapa,
             {'exato': 0, 'vencedor': 0, 'errou': 0, 'pts': 0, 'total': 0})
        ef[tipo] += 1
        ef['pts']   += pts
        ef['total'] += 1
        dist_pontos[pts] = dist_pontos.get(pts, 0) + 1

    total_c_pal = taxa['exato'] + taxa['vencedor'] + taxa['errou']
    taxa.update({
        'total_encerrados': len(jogos),
        'total_c_palpite':  total_c_pal,
        'pct_exato':    round(taxa['exato']    / total_c_pal * 100, 1) if total_c_pal else 0,
        'pct_vencedor': round(taxa['vencedor'] / total_c_pal * 100, 1) if total_c_pal else 0,
        'pct_errou':    round(taxa['errou']    / total_c_pal * 100, 1) if total_c_pal else 0,
    })

    # Streak — contagem da sequência mais recente
    streak_count = 0
    streak_tipo  = None
    for resultado in reversed(historico_streak):
        if resultado == 'sem_palpite':
            break
        if streak_tipo is None:
            streak_tipo  = resultado
            streak_count = 1
        elif resultado == streak_tipo:
            streak_count += 1
        else:
            break

    # Por fase: converte para array ordenado (apenas fases com jogos)
    por_fase_array = []
    for e in etapas_ordem:
        d = por_fase.get(e, {})
        if d.get('total', 0) > 0:
            por_fase_array.append({
                'etapa': etapa_abrev.get(e, e),
                'exato':    d['exato'],
                'vencedor': d['vencedor'],
                'errou':    d['errou'],
                'pts':      d['pts'],
                'total':    d['total'],
            })

    # ── COLETIVO ───────────────────────────────────────────────────────────────

    # Heatmap: últimos 20 jogos encerrados × todos usuários
    jogos_hm = jogos[-20:]
    hm_labels = [f"{j['time1']} x {j['time2']}" for j in jogos_hm]
    hm_linhas = []
    for u in usuarios:
        celulas = []
        for j in jogos_hm:
            pal = mapa.get(u['id'], {}).get(j['jogo_id'])
            if pal:
                try:
                    pts, tipo = _pts_tipo(j['gols_time1_real'], j['gols_time2_real'], pal[0], pal[1])
                    celulas.append({'tipo': tipo, 'pts': pts,
                                    'label': f"{pal[0]}x{pal[1]}", 'pts_label': f"+{pts}pt"})
                except (ValueError, TypeError):
                    celulas.append({'tipo': 'sem_palpite', 'pts': 0, 'label': '—', 'pts_label': ''})
            else:
                celulas.append({'tipo': 'sem_palpite', 'pts': 0, 'label': '—', 'pts_label': ''})
        hm_linhas.append({'login': u['login'], 'uid': u['id'], 'celulas': celulas})

    # Azarão: jogos onde > 50 % dos apostadores erraram
    azarao = []
    for j in jogos:
        tot = err = 0
        for u in usuarios:
            pal = mapa.get(u['id'], {}).get(j['jogo_id'])
            if pal:
                try:
                    _, tipo = _pts_tipo(j['gols_time1_real'], j['gols_time2_real'], pal[0], pal[1])
                    tot += 1
                    if tipo == 'errou':
                        err += 1
                except (ValueError, TypeError):
                    pass
        if tot > 0 and err / tot > 0.5:
            azarao.append({
                'label':     f"{j['time1']} x {j['time2']}",
                'resultado': f"{j['gols_time1_real']} x {j['gols_time2_real']}",
                'pct_erro':  round(err / tot * 100),
                'erros': err, 'total': tot,
            })
    azarao.sort(key=lambda x: x['pct_erro'], reverse=True)

    # Palpites mais comuns: últimos 10 jogos encerrados
    palpites_comuns = []
    for j in jogos[-10:]:
        jid = j['jogo_id']
        cont = {}
        for u in usuarios:
            pal = mapa.get(u['id'], {}).get(jid)
            if pal:
                key = f"{pal[0]}x{pal[1]}"
                cont[key] = cont.get(key, 0) + 1
        tot = sum(cont.values())
        if not tot:
            continue
        resultado_real = f"{j['gols_time1_real']}x{j['gols_time2_real']}"
        opcoes = sorted(
            [{'placar': k, 'count': v, 'pct': round(v / tot * 100),
              'acertou': k == resultado_real}
             for k, v in cont.items()],
            key=lambda x: x['count'], reverse=True
        )
        palpites_comuns.append({
            'label':         f"{j['time1']} x {j['time2']}",
            'resultado_real': resultado_real,
            'opcoes':         opcoes[:5],
            'total':          tot,
        })

    # Acertos comparativo: exatos e vencedores por jogador (mutuamente exclusivos)
    acertos_jogadores = []
    for u in usuarios:
        exatos = 0
        vencedores = 0
        total_pal = 0
        total_pts = 0.0
        for j in jogos:
            pal = mapa.get(u['id'], {}).get(j['jogo_id'])
            if pal is None:
                continue
            try:
                pts, tipo = _pts_tipo(j['gols_time1_real'], j['gols_time2_real'], pal[0], pal[1])
            except (ValueError, TypeError):
                continue
            total_pal += 1
            total_pts += pts * multiplicador_da_fase(j['etapa'])
            if tipo == 'exato':
                exatos += 1
            elif tipo == 'vencedor':
                vencedores += 1
        acertos_jogadores.append({
            'login': u['login'],
            'exatos': exatos,
            'vencedores': vencedores,
            'total_palpites': total_pal,
            'total_pts': round(total_pts, 1),
        })

    # Posição no ranking geral (por pontos com multiplicador)
    sorted_pts = sorted(acertos_jogadores, key=lambda x: x['total_pts'], reverse=True)
    for i, u_a in enumerate(sorted_pts):
        u_a['pos_ranking'] = i + 1

    return jsonify({
        'individual': {
            'taxa_geral':  taxa,
            'por_fase':    por_fase_array,
            'streak':      {'count': streak_count, 'tipo': streak_tipo,
                            'historico': historico_streak[-20:]},
            'pts_por_jogo': pts_por_jogo,
            'distribuicao': {str(k): v for k, v in sorted(dist_pontos.items())},
        },
        'coletivo': {
            'heatmap':        {'jogos': hm_labels, 'linhas': hm_linhas},
            'azarao':         azarao[:8],
            'palpites_comuns': list(reversed(palpites_comuns)),  # mais recente primeiro
            'acertos':        acertos_jogadores,
        }
    })


# 🚪 ROTA: Logout
@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# Garante que a migração rode tanto no gunicorn (Render) quanto localmente
with app.app_context():
    inicializar_db()

if __name__ == '__main__':
    app.run(debug=True)
