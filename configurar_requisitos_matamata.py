import os
import sqlite3
import psycopg2

def obter_conexao():
    url_banco = os.environ.get('DATABASE_URL')
    if url_banco:
        if url_banco.startswith("postgres://"):
            url_banco = url_banco.replace("postgres://", "postgresql://", 1)
        return psycopg2.connect(url_banco), True
    return sqlite3.connect('bolao.db'), False

def configurar():
    conn, is_postgres = obter_conexao()
    cursor = conn.cursor()
    placeholder = '%s' if is_postgres else '?'
    
    # Dicionário com o mapeamento exato que você me passou
    confrontos_iniciais = {
        # 16-avos (Armazenamos as regras nos campos de time para o motor ler)
        'Jogo_73': ('2A', '2B'),
        'Jogo_74': ('1E', '3A/B/C/D/F'),
        'Jogo_75': ('1F', '2C'),
        'Jogo_76': ('1C', '2F'),
        'Jogo_77': ('1I', '3C/D/F/G/H'),
        'Jogo_78': ('2E', '2I'),
        'Jogo_79': ('1A', '3C/E/F/H/I'),
        'Jogo_80': ('1L', '3E/H/I/J/K'),
        'Jogo_81': ('1D', '3B/E/F/I/J'),
        'Jogo_82': ('1G', '3A/E/H/I/J'),
        'Jogo_83': ('2K', '2L'),
        'Jogo_84': ('1H', '2J'),
        'Jogo_85': ('1B', '3E/F/G/I/J'),
        'Jogo_86': ('1J', '2H'),
        'Jogo_87': ('1K', '3D/E/I/J/L'),
        'Jogo_88': ('2D', '2G'),
        
        # Oitavas
        'Jogo_89': ('V_74', 'V_77'),
        'Jogo_90': ('V_73', 'V_75'),
        'Jogo_91': ('V_76', 'V_78'),
        'Jogo_92': ('V_79', 'V_80'),
        'Jogo_93': ('V_83', 'V_84'),
        'Jogo_94': ('V_81', 'V_82'),
        'Jogo_95': ('V_86', 'V_88'),
        'Jogo_96': ('V_85', 'V_87'),
        
        # Quartas
        'Jogo_97': ('V_89', 'V_90'),
        'Jogo_98': ('V_93', 'V_94'),
        'Jogo_99': ('V_91', 'V_92'),
        'Jogo_100': ('V_95', 'V_96'),
        
        # Semis
        'Jogo_101': ('V_97', 'V_98'),
        'Jogo_102': ('V_99', 'V_100'),
        
        # Finais
        'Jogo_103': ('P_101', 'P_102'), # P_ significa Perdedor do jogo
        'Jogo_104': ('V_101', 'V_102')  # V_ significa Vencedor do jogo
    }
    
    print("🔄 Atualizando definições de chaveamento no banco de dados...")
    
    for jogo_id, (t1, t2) in confrontos_iniciais.items():
        query = f'''
            UPDATE jogos 
            SET time1 = {placeholder}, time2 = {placeholder}, flag_code_time1 = 'un', flag_code_time2 = 'un'
            WHERE jogo_id = {placeholder}
        '''
        cursor.execute(query, (t1, t2, jogo_id))
        
    conn.commit()
    conn.close()
    print("✅ Banco de dados preparado! Agora o motor de chaveamento sabe ler as dependências de cada vaga.")

if __name__ == '__main__':
    configurar()