import pandas as pd
import sqlite3
import os
import psycopg2

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
        return sqlite3.connect('bolao.db'), False

def importar_csv_para_banco():
    conn, is_postgres = obter_conexao()
    cursor = conn.cursor()
    
    placeholder = '%s' if is_postgres else '?'
    
    print(f"⏳ Conectado ao banco de dados ({'PostgreSQL' if is_postgres else 'SQLite'}). Lendo arquivos CSV...")
    try:
        df_partidas = pd.read_csv('archive/partidas.csv', sep=';')
        df_times = pd.read_csv('archive/times.csv', sep=';')
        df_estagios = pd.read_csv('archive/estagios_copa.csv', sep=';')
        df_cities = pd.read_csv('archive/host_cities.csv', sep=',') 
    except FileNotFoundError as e:
        print(f"❌ Erro: Arquivo não encontrado. Verifique os nomes na pasta.\n{e}")
        conn.close()
        return

    print("🧼 Limpando e padronizando chaves de cruzamento...")
    # Remove espaços invisíveis dos nomes das colunas
    df_partidas.columns = df_partidas.columns.str.strip()
    df_times.columns = df_times.columns.str.strip()
    df_estagios.columns = df_estagios.columns.str.strip()
    df_cities.columns = df_cities.columns.str.strip()

    # Força a conversão das colunas de ID para String tirando valores nulos ou flutuantes (ex: 1.0 -> 1)
    for col in ['home_team_id', 'away_team_id', 'stage_id', 'city_id']:
        df_partidas[col] = df_partidas[col].fillna(0).astype(float).astype(int).astype(str)
        
    df_times['id'] = df_times['id'].fillna(0).astype(float).astype(int).astype(str)
    df_estagios['id'] = df_estagios['id'].fillna(0).astype(float).astype(int).astype(str)
    df_cities['id'] = df_cities['id'].fillna(0).astype(float).astype(int).astype(str)

    print("🧠 Cruzando os dados dos arquivos incluindo os Códigos FIFA...")
    
    # 1. Cruzar o Time da Casa
    df_juntos = pd.merge(df_partidas, df_times[['id', 'team_name', 'flag_code']], left_on='home_team_id', right_on='id', how='left')
    df_juntos = df_juntos.rename(columns={'team_name': 'time1', 'flag_code': 'flag_code_time1'}).drop(columns=['id_y'])

    # 2. Cruzar o Time Visitante
    df_juntos = pd.merge(df_juntos, df_times[['id', 'team_name', 'flag_code']], left_on='away_team_id', right_on='id', how='left')
    df_juntos = df_juntos.rename(columns={'team_name': 'time2', 'flag_code': 'flag_code_time2'}).drop(columns=['id'])

    # 3. Cruzar a Etapa da Copa
    df_juntos = pd.merge(df_juntos, df_estagios[['id', 'stage_name']], left_on='stage_id', right_on='id', how='left')
    df_juntos = df_juntos.rename(columns={'stage_name': 'etapa'}).drop(columns=['id'])

    # 4. Cruzar a Cidade Sede
    df_juntos = pd.merge(df_juntos, df_cities[['id', 'city_name']], left_on='city_id', right_on='id', how='left')
    df_juntos = df_juntos.rename(columns={'city_name': 'cidade'}).drop(columns=['id'])

    print("🛠️ Reiniciando a tabela de jogos com suporte a bandeiras...")
    cursor.execute('DROP TABLE IF EXISTS jogos CASCADE;') # Adicionado CASCADE para limpar dependências se houver no Postgres
    
    cursor.execute('''
        CREATE TABLE jogos (
            jogo_id TEXT PRIMARY KEY,
            time1 TEXT NOT NULL,
            time2 TEXT NOT NULL,
            flag_code_time1 TEXT,
            flag_code_time2 TEXT,
            gols_time1_real INTEGER,
            gols_time2_real INTEGER,
            status TEXT DEFAULT 'Pendente',
            etapa TEXT NOT NULL,
            data_hora TEXT NOT NULL,
            cidade TEXT
        )
    ''')
    
    print("🚀 Inserindo as partidas oficiais no Bolão...")
    contagem = 0
    for _, linha in df_juntos.iterrows():
        t1 = str(linha['time1']) if pd.notna(linha['time1']) else "A definir"
        t2 = str(linha['time2']) if pd.notna(linha['time2']) else "A definir"
        
        code1 = str(linha['flag_code_time1']).strip().lower() if pd.notna(linha['flag_code_time1']) else 'un'
        code2 = str(linha['flag_code_time2']).strip().lower() if pd.notna(linha['flag_code_time2']) else 'un'
        
        etapa_nome = str(linha['etapa']) if pd.notna(linha['etapa']) else "Fase de Grupos"
        cidade_nome = str(linha['cidade']) if pd.notna(linha['cidade']) else "A definir"
        
        jogo_id = f"Jogo_{linha['match_number']}"
        data_hora = str(linha['kickoff_at'])
        
        if is_postgres:
            query = f'''
                INSERT INTO jogos (jogo_id, time1, time2, flag_code_time1, flag_code_time2, etapa, data_hora, status, cidade)
                VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, 'Pendente', {placeholder})
                ON CONFLICT (jogo_id) DO NOTHING
            '''
        else:
            query = f'''
                INSERT OR IGNORE INTO jogos (jogo_id, time1, time2, flag_code_time1, flag_code_time2, etapa, data_hora, status, cidade)
                VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, 'Pendente', {placeholder})
            '''
            
        cursor.execute(query, (jogo_id, t1, t2, code1, code2, etapa_nome, data_hora, cidade_nome))
        contagem += 1
        
    conn.commit()
    conn.close()
    print(f"✅ Sucesso! {contagem} partidas estruturadas com códigos de bandeiras.")

if __name__ == '__main__':
    importar_csv_para_banco()