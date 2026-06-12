from flask import Flask, render_template, request, redirect, url_for, flash, session
import sqlite3
from datetime import datetime, timedelta
from pontuacao import calcular_pontos
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = 'chave_secreta_copa_2026_super_protegida'

def obter_conexao_db():
    conn = sqlite3.connect('bolao.db')
    conn.row_factory = sqlite3.Row
    return conn

def inicializar_db():
    conn = obter_conexao_db()
    cursor = conn.cursor()
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
    # Tabela jogos atualizada
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
        # 🔍 Buscamos o usuário apenas pelo login
        usuario = conn.execute('SELECT * FROM usuarios WHERE login = ?', (login_user,)).fetchone()
        conn.close()
        
        # 🔒 Se o usuário existir, comparamos a senha digitada com o hash salvo no banco
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
        # Ajustado para bater com os nomes do formulário moderno (usuario_login e usuario_senha)
        login_user = request.form['usuario_login'].strip()
        senha_user = request.form['usuario_senha'].strip()
        
        if not login_user or not senha_user:
            flash('Preencha todos os campos!')
            return render_template('cadastro.html')
            
        # 🔒 Cria o hash seguro e indestrutível da senha digitada
        senha_criptografada = generate_password_hash(senha_user)
            
        conn = obter_conexao_db()
        cursor = conn.cursor()
        try:
            # Gravando a senha_criptografada no banco de dados
            cursor.execute('INSERT INTO usuarios (login, senha) VALUES (?, ?)', (login_user, senha_criptografada))
            conn.commit()
            conn.close()
            flash('Cadastro realizado com sucesso! Faça seu login.')
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            conn.close()
            flash('Esse login já existe! Escolha outro.')
            
    return render_template('cadastro.html')

# 📋 ROTA: Ambiente do Usuário (Versão Blindada contra Erros de Carga)
@app.route('/palpites', methods=['GET', 'POST'])
def palpites():
    if 'usuario_id' not in session:
        return redirect(url_for('login'))
        
    usuario_id = session['usuario_id']
    conn = sqlite3.connect('bolao.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # 💾 SE O USUÁRIO CLICOU EM SALVAR
    if request.method == 'POST':
        print("📥 Formulário recebido! Processando palpites...")
        for chave, valor in request.form.items():
            if chave.startswith('gols1_'):
                # Extrai o ID do jogo (ex: se vier "gols1_Jogo_1", o jogo_id será "Jogo_1")
                jogo_id = chave.replace('gols1_', '')
                gols_t1 = valor
                gols_t2 = request.form.get(f'gols2_{jogo_id}')

                # Validação estrita: só grava se o usuário digitou ambos os campos
                if gols_t1 != '' and gols_t2 != '' and gols_t1 is not None and gols_t2 is not None:
                    try:
                        # 🚨 NOVA DEFESA ANTI-NEGATIVOS: ignora ou barra se menor que zero
                        if int(gols_t1) < 0 or int(gols_t2) < 0:
                            print(f"⚠️ Tentativa de palpite negativo ignorada para o jogo {jogo_id}")
                            continue # Pula este jogo e não salva nada incorreto

                        cursor.execute('SELECT 1 FROM palpites WHERE usuario_id = ? AND jogo_id = ?', (usuario_id, jogo_id))
                        existe = cursor.fetchone()

                        if existe:
                            cursor.execute('''
                                UPDATE palpites 
                                SET gols_time1 = ?, gols_time2 = ? 
                                WHERE usuario_id = ? AND jogo_id = ?
                            ''', (int(gols_t1), int(gols_t2), usuario_id, jogo_id))
                        else:
                            cursor.execute('''
                                INSERT INTO palpites (usuario_id, jogo_id, gols_time1, gols_time2) 
                                VALUES (?, ?, ?, ?)
                            ''', (usuario_id, jogo_id, int(gols_t1), int(gols_t2)))
                    except Exception as e:
                        print(f"❌ Erro ao inserir/atualizar jogo {jogo_id}: {e}")
        
        conn.commit()
        print("💾 Todos os palpites foram validados e commitados no banco!")
        flash('Palpites salvos com sucesso!')
        return redirect(url_for('palpites'))

    # 🔍 BUSCA DOS JOGOS
    cursor.execute('''
        SELECT 
            j.jogo_id, j.time1, j.time2, j.etapa, j.data_hora, j.cidade, j.status,
            j.flag_code_time1, j.flag_code_time2, j.gols_time1_real, j.gols_time2_real,
            p.gols_time1 AS gols_time1_palpite, p.gols_time2 AS gols_time2_palpite
        FROM jogos j
        LEFT JOIN palpites p ON j.jogo_id = p.jogo_id AND p.usuario_id = ?
        ORDER BY j.data_hora ASC
    ''', (usuario_id,))
    
    jogos = cursor.fetchall()
    
    # 📁 SUA ESTRUTURA DE ETAPAS OFICIAIS ORGANIZADAS
    etapas_ordem = [
        "Fase de Grupos Rodada 1", 
        "Fase de Grupos Rodada 2", 
        "Fase de Grupos Rodada 3",
        "Dezesseis-avos de final", 
        "Oitavas de final", 
        "Quartas de final", 
        "Semifinais",
        "Disputa de terceiro lugar", 
        "Final"
    ]
    
    # Inicializa o dicionário com a ordem correta
    jogos_agrupados = {etapa: [] for etapa in etapas_ordem}
    
    # Distribui os jogos nas chaves correspondentes e calcula os bônus visuais
    for row in jogos:
        # Transformamos o row do SQLite em um dicionário comum para podermos adicionar novas chaves dinamicamente
        jogo = dict(row)
        etapa_jogo = jogo['etapa']
        
        # Inicializa as variáveis de bônus para a tela
        jogo['acertou_placar'] = False
        jogo['acertou_vencedor'] = False
        jogo['bonus_saldo'] = False
        jogo['bonus_gols'] = False
        jogo['pontos_faturados'] = 0
        
        # 🧠 Se o jogo já acabou e o usuário deu um palpite, calcula o que ele acertou
        if jogo['status'] == 'Encerrado' and jogo['gols_time1_real'] is not None and jogo['gols_time1_palpite'] is not None:
            try:
                g1_real = int(jogo['gols_time1_real'])
                g2_real = int(jogo['gols_time2_real'])
                g1_palp = int(jogo['gols_time1_palpite'])
                g2_palp = int(jogo['gols_time2_palpite'])
                
                # 1. Placar Exato
                if g1_real == g1_palp and g2_real == g2_palp:
                    jogo['acertou_placar'] = True
                    jogo['pontos_faturados'] = 10
                else:
                    venc_real = "t1" if g1_real > g2_real else "t2" if g2_real > g1_real else "empate"
                    venc_palp = "t1" if g1_palp > g2_palp else "t2" if g2_palp > g1_palp else "empate"
                    
                    # 2. Vencedor ou Empate
                    if venc_real == venc_palp:
                        jogo['acertou_vencedor'] = True
                        jogo['pontos_faturados'] += 5
                        
                        # Bônus: Saldo de Gols
                        if (g1_real - g2_real) == (g1_palp - g2_palp):
                            jogo['bonus_saldo'] = True
                            jogo['pontos_faturados'] += 2
                            
                    # Bônus: Gols de uma das equipes
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
    usuarios = conn.execute('SELECT id, login FROM usuarios').fetchall()
    jogos_encerrados = conn.execute('SELECT * FROM jogos WHERE status = "Encerrado"').fetchall()
    todos_palpites = conn.execute('SELECT * FROM palpites').fetchall()
    conn.close()
    
    tabela_pontos = {u['id']: {'id': u['id'], 'login': u['login'], 'pontos': 0} for u in usuarios}
    mapa_jogos = {j['jogo_id']: j for j in jogos_encerrados}
    
    for p in todos_palpites:
        jogo_id = p['jogo_id']
        usr_id = p['usuario_id']
        
        if jogo_id in mapa_jogos and usr_id in tabela_pontos:
            jogo = mapa_jogos[jogo_id]
            
            # 🛡️ SEGURANÇA: Se o admin encerrou mas esqueceu de digitar o placar, ignora para não quebrar
            if jogo['gols_time1_real'] is None or jogo['gols_time2_real'] is None:
                continue
                
            # 🛡️ SEGURANÇA: Garante que tudo seja tratado estritamente como INTEIRO para as contas baterem
            try:
                g1_real = int(jogo['gols_time1_real'])
                g2_real = int(jogo['gols_time2_real'])
                g1_palp = int(p['gols_time1'])
                g2_palp = int(p['gols_time2'])
            except (ValueError, TypeError):
                continue # Se houver algum valor corrompido ou vazio, pula o palpite com segurança
            
            pontos_do_palpite = 0
            
            # Critério 1: Placar Exato (10 pontos)
            if g1_real == g1_palp and g2_real == g2_palp:
                pontos_do_palpite = 10
            else:
                # Determina o vencedor/empate real e do palpite
                venc_real = "t1" if g1_real > g2_real else "t2" if g2_real > g1_real else "empate"
                venc_palp = "t1" if g1_palp > g2_palp else "t2" if g2_palp > g1_palp else "empate"
                
                # Critério 2: Vencedor ou Empate (5 pontos)
                if venc_real == venc_palp:
                    pontos_do_palpite += 5
                    
                    # Bônus: Saldo de Gols (+2 pontos)
                    if (g1_real - g2_real) == (g1_palp - g2_palp):
                        pontos_do_palpite += 2
                        
                # Bônus: Gols de uma das equipes (+1 ponto)
                if g1_real == g1_palp or g2_real == g2_palp:
                    pontos_do_palpite += 1
                    
            tabela_pontos[usr_id]['pontos'] += pontos_do_palpite

    ranking_ordenado = list(tabela_pontos.values())
    ranking_ordenado.sort(key=lambda x: x['pontos'], reverse=True)
    # ... (fim do cálculo dos pontos)
    ranking_ordenado = list(tabela_pontos.values())
    ranking_ordenado.sort(key=lambda x: x['pontos'], reverse=True)
    
    print(f"📊 DADOS ENVIADOS PARA O HTML: {ranking_ordenado}") # 👈 ADICIONE ESTE PRINT AQUI!
    
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
    
    if request.method == 'POST':
        cursor = conn.cursor()
        
        # Lê os inputs ocultos (hidden) que o seu HTML envia ao clicar no botão
        jogo_id = request.form.get('jogo_id')
        acao = request.form.get('acao')
        
        print(f"\n=== 📥 COMANDO ADMIN RECEBIDO ===")
        print(f"Jogo ID: {jogo_id} | Ação clicada: {acao}")
        
        # Cenário 1: Clicou no botão de Iniciar Partida
        if acao == 'iniciar':
            cursor.execute('''
                UPDATE jogos 
                SET status = "Em Andamento" 
                WHERE jogo_id = ?
            ''', (jogo_id,))
            print(f"🏃 Partida {jogo_id} alterada para 'Em Andamento'.")
            flash('Partida iniciada! Palpites trancados.')
            
        # Cenário 2: Preencheu o placar e clicou em Encerrado
        elif acao == 'encerrar':
            gols_t1 = request.form.get('gols_time1_real')
            gols_t2 = request.form.get('gols_time2_real')
            
            print(f"⚽ Placar digitado: {gols_t1} X {gols_t2}")
            
            if gols_t1 is not None and gols_t2 is not None and gols_t1.strip() != '' and gols_t2.strip() != '':
                # 🎯 CORREÇÃO AQUI: Removido o 'OR id = ?' que quebrava o banco
                cursor.execute('''
                    UPDATE jogos 
                    SET gols_time1_real = ?, gols_time2_real = ?, status = "Encerrado" 
                    WHERE jogo_id = ?
                ''', (int(gols_t1), int(gols_t2), jogo_id))
                
                print(f"✅ Jogo {jogo_id} ENCERRADO. Linhas afetadas: {cursor.rowcount}")
                flash('Resultado gravado e jogo encerrado com sucesso!')
            else:
                flash('Erro: Você precisa digitar os gols antes de encerrar!')
                
        conn.commit()
        conn.close()
        print("=== 💾 ALTERAÇÕES SALVAS COM COMMIT ===\n")
        
        # Recarrega a própria página do admin para mostrar as mudanças atualizadas
        return redirect(url_for('admin'))
        
    # Código do GET: Busca os jogos para listar na tela
    jogos = conn.execute('SELECT * FROM jogos ORDER BY data_hora ASC').fetchall()
    conn.close()
    
    # Suas etapas oficiais organizadas sem hífens
    etapas_ordem = [
        "Fase de Grupos Rodada 1", 
        "Fase de Grupos Rodada 2", 
        "Fase de Grupos Rodada 3",
        "Dezesseis-avos de final", 
        "Oitavas de final", 
        "Quartas de final", 
        "Semifinais",
        "Disputa de terceiro lugar", 
        "Final"
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
    
    # 1. Garante que o amigo_id seja tratado como INTEIRO para a busca no banco
    try:
        amigo_id_int = int(amigo_id)
    except ValueError:
        amigo_id_int = amigo_id

    # Busca o nome do amigo
    amigo = conn.execute('SELECT login FROM usuarios WHERE id = ?', (amigo_id_int,)).fetchone()
    if not amigo:
        conn.close()
        return "Usuário não encontrado", 404
        
    # Busca todos os jogos e os palpites do amigo usando o ID correto
    jogos = conn.execute('SELECT * FROM jogos ORDER BY data_hora ASC').fetchall()
    palpites_busca = conn.execute('SELECT * FROM palpites WHERE usuario_id = ?', (amigo_id_int,)).fetchall()
    conn.close()
    
    # Mapeia os palpites indexados pelo jogo_id
    meus_palpites = {p['jogo_id']: (p['gols_time1'], p['gols_time2']) for p in []}
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
        
        # Resgata o palpite do amigo
        palpite = meus_palpites.get(j_id)
        jogo['gols_time1_palpite'] = palpite[0] if palpite else None
        jogo['gols_time2_palpite'] = palpite[1] if palpite else None
        
        # 🔑 Tratamento flexível para a data do banco
        horario_jogo = None
        if jogo.get('data_hora'):
            data_str = str(jogo['data_hora']).strip()
            for formato in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%d/%m/%Y %H:%M'):
                try:
                    horario_jogo = datetime.strptime(data_str, formato)
                    break
                except ValueError:
                    continue
                
        # 🔒 VALIDAÇÃO DA TRAVA (Se o status mudou ou se o tempo expirou)
        jogo_trancado = False
        
        # Se no banco o status estiver diferente de 'Pendente' (ex: 'Em Andamento', 'Encerrado', 'Trancado')
        if str(jogo.get('status', '')).strip() != 'Pendente':
            jogo_trancado = True
        # Se a validação por hora passar
        elif horario_jogo and agora >= (horario_jogo - timedelta(hours=1)):
            jogo_trancado = True

        # 🚨 SE MESMO TRANCADO ELE NÃO APARECER, COMENTE AS DUAS LINHAS ABAIXO PARA TESTAR:
        if not jogo_trancado:
            continue

        # CÁLCULO DE PONTOS
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
        cursor = conn.cursor()
        
        cursor.execute('SELECT senha FROM usuarios WHERE id = ?', (usuario_id,))
        usuario = cursor.fetchone()
        
        # 🔐 A MÁGICA DA CRIPTOGRAFIA ACONTECE AQUI:
        # check_password_hash traduz o hash do banco e compara com a digitada
        if usuario and check_password_hash(usuario['senha'], senha_atual):
            
            # Geramos um novo hash seguro para a nova senha antes de salvar
            nova_senha_criptografada = generate_password_hash(nova_senha)
            
            cursor.execute('UPDATE usuarios SET senha = ? WHERE id = ?', (nova_senha_criptografada, usuario_id))
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