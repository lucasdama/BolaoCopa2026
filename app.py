from flask import Flask, render_template, request, redirect, url_for, flash, session
import os
import sqlite3
import psycopg2
from psycopg2.extras import DictCursor
from datetime import datetime, timedelta
from pontuacao import calcular_pontos
from werkzeug.security import generate_password_hash, check_password_hash

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

# 📝 ADAPTADOR DINÂMICO DE QUERIES (?, ? vs %s, %s)
def preparar_query(query):
    if os.environ.get('DATABASE_URL'):
        return query.replace('?', '%s')
    return query

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
    query_select = preparar_query('''
        SELECT 
            j.jogo_id, j.time1, j.time2, j.etapa, j.data_hora, j.cidade, j.status,
            j.gols_time1_real, j.gols_time2_real,
            p.gols_time1 AS gols_time1_palpite, p.gols_time2 AS gols_time2_palpite
        FROM jogos j
        LEFT JOIN palpites p ON j.jogo_id = p.jogo_id AND p.usuario_id = ?
        ORDER BY j.data_hora ASC
    ''')
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
                
                if g1_real == g1_palp and g2_real == g2_palp:
                    jogo['acertou_placar'] = True
                    jogo['pontos_faturados'] = 10
                else:
                    venc_real = "t1" if g1_real > g2_real else "t2" if g2_real > g1_real else "empate"
                    venc_palp = "t1" if g1_palp > g2_palp else "t2" if g2_palp > g1_palp else "empate"
                    
                    if venc_real == venc_palp:
                        jogo['acertou_vencedor'] = True
                        jogo['pontos_faturados'] += 5
                        if (g1_real - g2_real) == (g1_palp - g2_palp):
                            jogo['bonus_saldo'] = True
                            jogo['pontos_faturados'] += 2
                            
                    if g1_real == g1_palp or g2_real == g2_palp:
                        jogo['bonus_gols'] = True
                        jogo['pontos_faturados'] += 1
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
            
            pontos_do_palpite = 0
            
            if g1_real == g1_palp and g2_real == g2_palp:
                pontos_do_palpite = 10
            else:
                venc_real = "t1" if g1_real > g2_real else "t2" if g2_real > g1_real else "empate"
                venc_palp = "t1" if g1_palp > g2_palp else "t2" if g2_palp > g1_palp else "empate"
                
                if venc_real == venc_palp:
                    pontos_do_palpite += 5
                    if (g1_real - g2_real) == (g1_palp - g2_palp):
                        pontos_do_palpite += 2
                        
                if g1_real == g1_palp or g2_real == g2_palp:
                    pontos_do_palpite += 1
                    
            tabela_pontos[usr_id]['pontos'] += pontos_do_palpite

    ranking_ordenado = list(tabela_pontos.values())
    ranking_ordenado.sort(key=lambda x: x['pontos'], reverse=True)
    
    print(f"📊 DADOS ENVIADOS PARA O HTML: {ranking_ordenado}")
    
    return render_template('ranking.html', usuarios_ranking=ranking_ordenado)

# 👑 ROTA: Painel do Administrador (Ajustada para o seu HTML original)
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
            query_init = preparar_query('UPDATE jogos SET status = "Em Andamento" WHERE jogo_id = ?')
            cursor.execute(query_init, (jogo_id,))
            print(f"🏃 Partida {jogo_id} alterada para 'Em Andamento'.")
            flash('Partida iniciada! Palpites trancados.')
            
        elif acao == 'encerrar':
            gols_t1 = request.form.get('gols_time1_real')
            gols_t2 = request.form.get('gols_time2_real')
            
            print(f"⚽ Placar digitado: {gols_t1} X {gols_t2}")
            
            if gols_t1 is not None and gols_t2 is not None and gols_t1.strip() != '' and gols_t2.strip() != '':
                query_end = preparar_query('''
                    UPDATE jogos 
                    SET gols_time1_real = ?, gols_time2_real = ?, status = "Encerrado" 
                    WHERE jogo_id = ?
                ''')
                cursor.execute(query_end, (int(gols_t1), int(gols_t2), jogo_id))
                print(f"✅ Jogo {jogo_id} ENCERRADO.")
                flash('Resultado gravado e jogo encerrado com sucesso!')
            else:
                flash('Erro: Você precisa digitar os gols antes de encerrar!')
                
        conn.commit()
        conn.close()
        print("=== 💾 ALTERAÇÕES SALVAS COM COMMIT ===\n")
        return redirect(url_for('admin'))
        
    cursor.execute('SELECT * FROM jogos ORDER BY data_hora ASC')
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

@app.route('/palpites_amigo/<amigo_id>')
def palpites_amigo(amigo_id):
    if 'usuario_id' not in session:
        return redirect(url_for('login'))
        
    conn = obter_conexao_db()
    cursor = obter_cursor(conn)
    
    try:
        amigo_id_int = int(amigo_id)
    except ValueError:
        amigo_id_int = amigo_id

    query_amigo = preparar_query('SELECT login FROM usuarios WHERE id = ?')
    cursor.execute(query_amigo, (amigo_id_int,))
    amigo = cursor.fetchone()
    
    if not amigo:
        conn.close()
        return "Usuário não encontrado", 404
        
    cursor.execute('SELECT * FROM jogos ORDER BY data_hora ASC')
    jogos = cursor.fetchall()
    
    query_palpites = preparar_query('SELECT * FROM palpites WHERE usuario_id = ?')
    cursor.execute(query_palpites, (amigo_id_int,))
    palpites_busca = cursor.fetchall()
    conn.close()
    
    meus_palpites = {}
    try:
        meus_palpites = {p['jogo_id']: (p['gols_time1'], p['gols_time2']) for p in palpites_busca}
    except Exception:
        pass
    
    etapas_ordem = [
        "Fase de Grupos Rodada 1", "Fase de Grupos Rodada 2", "Fase de Grupos Rodada 3",
        "Dezesseis-avos de final", "Oitavas de final", "Quartas de final", 
        "Semifinais", "Disputa de terceiro lugar", "Final"
    ]
    
    jogos_agrupados = {etapa: [] for etapa in etapas_ordem}
    agora = datetime.now()

    for row in jogos:
        jogo = dict(row)
        j_id = jogo['jogo_id']
        etapa_jogo = jogo['etapa']
        
        jogo['acertou_placar'] = False
        jogo['acertou_vencedor'] = False
        jogo['bonus_saldo'] = False
        jogo['bonus_gols'] = False
        jogo['pontos_faturados'] = 0
        
        palpite = meus_palpites.get(j_id)
        jogo['gols_time1_palpite'] = palpite[0] if palpite else None
        jogo['gols_time2_palpite'] = palpite[1] if palpite else None
        
        horario_jogo = None
        if jogo.get('data_hora'):
            data_str = str(jogo['data_hora']).strip()
            for formato in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%d/%m/%Y %H:%M'):
                try:
                    horario_jogo = datetime.strptime(data_str, formato)
                    break
                except ValueError:
                    continue
                
        jogo_trancado = False
        if str(jogo.get('status', '')).strip() != 'Pendente':
            jogo_trancado = True
        elif horario_jogo and agora >= (horario_jogo - timedelta(hours=1)):
            jogo_trancado = True

        if not jogo_trancado:
            continue

        if jogo['status'] == 'Encerrado' and jogo['gols_time1_real'] is not None and jogo['gols_time1_palpite'] is not None and jogo['gols_time1_palpite'] != '':
            try:
                g1_real = int(jogo['gols_time1_real'])
                g2_real = int(jogo['gols_time2_real'])
                g1_palp = int(jogo['gols_time1_palpite'])
                g2_palp = int(jogo['gols_time2_palpite'])
                
                if g1_real == g1_palp and g2_real == g2_palp:
                    jogo['acertou_placar'] = True
                    jogo['pontos_faturados'] = 10
                else:
                    venc_real = "t1" if g1_real > g2_real else "t2" if g2_real > g1_real else "empate"
                    venc_palp = "t1" if g1_palp > g2_palp else "t2" if g2_palp > g1_palp else "empate"
                    
                    if venc_real == venc_palp:
                        jogo['acertou_vencedor'] = True
                        jogo['pontos_faturados'] += 5
                        if (g1_real - g2_real) == (g1_palp - g2_palp):
                            jogo['bonus_saldo'] = True
                            jogo['pontos_faturados'] += 2
                            
                    if g1_real == g1_palp or g2_real == g2_palp:
                        jogo['bonus_gols'] = True
                        jogo['pontos_faturados'] += 1
            except (ValueError, TypeError):
                pass

        if etapa_jogo not in jogos_agrupados:
            jogos_agrupados[etapa_jogo] = []
        jogos_agrupados[etapa_jogo].append(jogo)

    return render_template('palpites_amigo.html', nome_amigo=amigo['login'], jogos_agrupados=jogos_agrupados)

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

# 🚪 ROTA: Logout
@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

if __name__ == '__main__':
    inicializar_db()
    app.run(debug=True)