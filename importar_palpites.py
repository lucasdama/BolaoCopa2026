import csv
import os
import sqlite3
from werkzeug.security import generate_password_hash

def importar_palpites_csv(caminho_csv):
    caminho_diretorio = os.path.dirname(os.path.abspath(__file__))
    caminho_banco = os.path.join(caminho_diretorio, 'bolao.db')
    
    conn = sqlite3.connect(caminho_banco)
    cursor = conn.cursor()
    
    senha_padrao_hash = generate_password_hash('copa2026')
    print(f"🚀 Conectado ao banco em: {caminho_banco}")
    
    # 🧼 PASSO ZERO: Limpa os palpites antigos errados (que estão salvos apenas como número puro)
    # Isso evita duplicar sujeira no banco de dados.
    cursor.execute("DELETE FROM palpites WHERE jogo_id NOT LIKE 'Jogo_%'")
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
                
                # 🎯 CORREÇÃO CRUCIAL: Transforma o número "1" no texto "Jogo_1"
                jogo_id = f"Jogo_{id_puro.strip()}"
                
                if gols_t1 is None or gols_t2 is None or gols_t1.strip() == '' or gols_t2.strip() == '':
                    continue
                
                # ─── PASSO 1: GARANTIR QUE O USUÁRIO EXISTE ───
                cursor.execute('SELECT id FROM usuarios WHERE login = ?', (nome_usuario,))
                usuario_registro = cursor.fetchone()
                
                if usuario_registro:
                    usuario_id = usuario_registro[0]
                else:
                    try:
                        cursor.execute('INSERT INTO usuarios (login, senha) VALUES (?, ?)', (nome_usuario, senha_padrao_hash))
                        usuario_id = cursor.lastrowid
                        print(f"👤 Usuário criado: {nome_usuario} (ID: {usuario_id})")
                    except sqlite3.IntegrityError:
                        cursor.execute('SELECT id FROM usuarios WHERE login = ?', (nome_usuario,))
                        usuario_id = cursor.fetchone()[0]

                # ─── PASSO 2: INSERIR OU ATUALIZAR O PALPITE ───
                cursor.execute('SELECT 1 FROM palpites WHERE usuario_id = ? AND jogo_id = ?', (usuario_id, jogo_id))
                palpite_existe = cursor.fetchone()
                
                if palpite_existe:
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