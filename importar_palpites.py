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
    
    try:
        # 🛠️ PASSO EXTRA: Garante a criação estrutural das tabelas antes de limpá-las ou usá-las
        if is_postgres:
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS usuarios (
                    id SERIAL PRIMARY KEY,
                    login TEXT UNIQUE NOT NULL,
                    senha TEXT NOT NULL,
                    pontos INTEGER DEFAULT 0,
                    admin INTEGER DEFAULT 0
                );
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS palpites (
                    id SERIAL PRIMARY KEY,
                    usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
                    jogo_id TEXT NOT NULL,
                    gols_time1 INTEGER NOT NULL,
                    gols_time2 INTEGER NOT NULL,
                    CONSTRAINT unico_palpite_por_jogo UNIQUE (usuario_id, jogo_id)
                );
            ''')
        else:
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS usuarios (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    login TEXT UNIQUE