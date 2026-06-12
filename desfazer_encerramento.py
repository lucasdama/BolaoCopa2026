import sqlite3
import os

def reabrir_jogos():
    caminho_diretorio = os.path.dirname(os.path.abspath(__file__))
    caminho_banco = os.path.join(caminho_diretorio, 'bolao.db')
    
    conn = sqlite3.connect(caminho_banco)
    cursor = conn.cursor()
    
    # IDs dos jogos que você quer reabrir
    jogos_para_reabrir = ('Jogo_1', 'Jogo_2')
    
    try:
        print(f"🔄 Reabrindo partidas no banco: {caminho_banco}...")
        
        # Atualiza o status para 'Pendente' e limpa os gols reais (para não interferir nos pontos)
        cursor.execute('''
            UPDATE jogos 
            SET status = 'Pendente', gols_time1_real = NULL, gols_time2_real = NULL
            WHERE jogo_id IN (?, ?)
        ''', jogos_para_reabrir)
        
        # Opcional: Se você já tinha rodado a lógica de pontos do admin, 
        # pode ser bom garantir que os pontos desses jogos voltem a não pontuar.
        # (Depende de como você estruturou sua tabela de pontos/apostas).
        
        conn.commit()
        print("🔓 Jogos 1 e 2 foram reabertos com sucesso! A edição está liberada para a galera.")
        
    except Exception as e:
        conn.rollback()
        print(f"❌ Erro ao tentar reabrir jogos: {e}")
    finally:
        conn.close()

if __name__ == '__main__':
    reabrir_jogos()