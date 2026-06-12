import csv
import os
import sqlite3
import psycopg2
from werkzeug.security import generate_password_hash

def obter_conexao():
    url_banco = os.environ.get('DATABASE_URL')
    if url_banco:
        # Conexão Produção (PostgreSQL na Render)
        if url_banco.startswith("postgres://"):
            url_banco = url_banco.replace("postgres://", "postgresql://", 1)
        if "sslmode=" not in url_banco:
            url_banco += "?sslmode=prefer"
        return psycopg2.connect(url_banco), True
    else:
        # Conexão Local (SQLite)
        caminho_diretorio = os.path.dirname(os.path.abspath(__file__))
        caminho_banco = os.path.join(caminho_diretorio, 'bolao.db')
        return sqlite3.connect(caminho_banco), False

def importar_palpites_csv(caminho_csv):
    conn, is_postgres = obter_conexao()
    cursor = conn.cursor()
    
    placeholder = '%s' if is_postgres else '?'
    senha_padrao_hash = generate_password_hash('copa2026')
    
    print(f"🚀 Conectado ao banco de dados: {'PostgreSQL (Render)' if is_postgres else 'SQLite (Local)'}")
    
    # 🧼 PASSO ZERO: Limpa os palpites antigos errados
    cursor.execute(f"DELETE FROM palpites WHERE jogo_id NOT LIKE 'Jogo_%%'")
    conn.commit()
    print("🧼 Limpeza de resíduos numéricos antigos concluída.")
    
    print("🚀 Iniciando importação de palpites corrigidos...")
    
    try:
        with open(caminho_csv, mode='r', encoding='utf-8-sig') as f:
            primeira_linha = f.readline()
            delimitador = ';' if ';' in primeira_linha else ','
            
        with open(caminho_csv, mode='r', encoding='utf-8-sig') as arquivo:
            leitor = csv.DictReader(arquivo, delimiter=delimitador)
            leitor.fieldnames = [field.strip().lower() for field in leitor.fieldnames]
            
            contador_sucesso = 0
            
            for index, linha in enumerate(leitor, start=2):
                nome_usuario = linha.get('usuarios') or linha.get('usuario')
                id_puro = linha.get('match_number') or linha.get('match')
                gols_t1 = linha.get('gols_time1_palpite') or linha.get('gols_time1')
                gols_t2 = linha.get('gols_time2_palpite') or linha.get('gols_time2')
                
                if not nome_usuario or not id_puro:
                    continue
                    
                nome_usuario = nome_usuario.strip()
                jogo_id = f"Jogo_{id_puro.strip()}"
                
                if gols_t1 is None or gols_t2 is None or gols_t1.strip() == '' or gols_t2.strip() == '':
                    continue
                
                # ─── PASSO 1: GARANTIR QUE O USUÁRIO EXISTE ───
                cursor.execute(f'SELECT id FROM usuarios WHERE login = {placeholder}', (nome_usuario,))
                usuario_registro = cursor.fetchone()
                
                if usuario_registro:
                    usuario_id = usuario_registro[0]
                else:
                    try:
                        if is_postgres:
                            # No Postgres, usamos RETURNING id para pegar a chave gerada pelo SERIAL
                            cursor.execute('INSERT INTO usuarios (login, senha) VALUES (%s, %s) RETURNING id', (nome_usuario, senha_padrao_hash))
                            usuario_id = cursor.fetchone()[0]
                        else:
                            cursor.execute('INSERT INTO usuarios (login, senha) VALUES (?, ?)', (nome_usuario, senha_padrao_hash))
                            usuario_id = cursor.lastrowid
                            
                        print(f"👤 Usuário criado: {nome_usuario} (ID: {usuario_id})")
                    except (sqlite3.IntegrityError, psycopg2.errors.UniqueViolation if is_postgres else Exception):
                        # Caso dê erro de concorrência/duplicidade, tenta buscar o ID novamente
                        if is_postgres:
                            conn.rollback() # Limpa o estado de erro da transação se for Postgres
                            cursor = conn.cursor()
                        cursor.execute(f'SELECT id FROM usuarios WHERE login = {placeholder}', (nome_usuario,))
                        usuario_id = cursor.fetchone()[0]

                # ─── PASSO 2: INSERIR OU ATUALIZAR O PALPITE ───
                cursor.execute(f'SELECT 1 FROM palpites WHERE usuario_id = {placeholder} AND jogo_id = {placeholder}', (usuario_id, jogo_id))
                palpite_existe = cursor.fetchone()
                
                if palpite_existe:
                    cursor.execute(f'''
                        UPDATE palpites 
                        SET gols_time1 = {placeholder}, gols_time2 = {placeholder} 
                        WHERE usuario_id = {placeholder} AND jogo_id = {placeholder}
                    ''', (int(gols_t1), int(gols_t2), usuario_id, jogo_id))
                else:
                    cursor.execute(f'''
                        INSERT INTO palpites (usuario_id, jogo_id, gols_time1, gols_time2) 
                        VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder})
                    ''', (usuario_id, jogo_id, int(gols_t1), int(gols_t2)))
                
                contador_sucesso += 1
                    
            conn.commit()
            print(f"\n✨ Sucesso total! {contador_sucesso} palpites foram devidamente vinculados no formato correto ('Jogo_X').")
            
    except Exception as e:
        conn.rollback()
        print(f"❌ Ocorreu um erro durante a importação: {e}")
    finally:
        conn.close()

if __name__ == '__main__':
    importar_palpites_csv('archive/palpites_iniciais.csv')