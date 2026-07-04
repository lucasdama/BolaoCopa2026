"""
Corrige o chaveamento do mata-mata a partir das Oitavas (Jogos 89 a 104)
conforme a tabela oficial da FIFA — banco de PRODUCAO (PostgreSQL/Render).

Uso:
    # Apenas mostra o que seria alterado (sem tocar nada):
    DATABASE_URL="<sua-string>" python corrigir_chaveamento_oitavas_prod.py --dry-run

    # Aplica a correcao (gera backup antes):
    DATABASE_URL="<sua-string>" python corrigir_chaveamento_oitavas_prod.py

Sem DATABASE_URL definida, roda contra o bolao.db local (SQLite) — util para teste.
A variavel DATABASE_URL deve ser definida na linha de comando — nunca hardcoded aqui.

Palpites existentes nos jogos afetados NAO sao alterados nem apagados;
eles sao apenas listados no final para decisao manual.
"""

import os
import sys
import json
import datetime
import sqlite3

# ─── Chave oficial (horarios de Brasilia, formato dd/mm/aaaa HH:MM) ──────────
# Oitavas: times ja definidos. IDs seguem a ordem cronologica dos jogos.
CONFRONTOS_OITAVAS = [
    # (jogo_id, time1, time2, flag1, flag2, data_hora)
    ("Jogo_89", "Canada",    "Marrocos",   "CA", "MC", "04/07/2026 14:00"),
    ("Jogo_90", "Paraguai",  "Franca",     "PY", "FR", "04/07/2026 18:00"),
    ("Jogo_91", "Brasil",    "Noruega",    "BR", "NO", "05/07/2026 17:00"),
    ("Jogo_92", "Mexico",    "Inglaterra", "MX", "GB", "05/07/2026 21:00"),
    ("Jogo_93", "Portugal",  "Espanha",    "PT", "ES", "06/07/2026 16:00"),
    ("Jogo_94", "EUA",       "Belgica",    "US", "BE", "06/07/2026 21:00"),
    ("Jogo_95", "Argentina", "Egito",      "AR", "EG", "07/07/2026 13:00"),
    ("Jogo_96", "Suica",     "Colombia",   "CH", "CO", "07/07/2026 17:00"),
]

# Fases seguintes: placeholders no padrao "Vencedor N"/"Perdedor N" que o motor
# de chaveamento (chaveamento.py) substitui automaticamente ao encerrar cada jogo.
CONFRONTOS_PLACEHOLDER = [
    # Quartas — mapeamento fixo da chave oficial
    ("Jogo_97",  "Vencedor 90",  "Vencedor 89",  "un", "un", "09/07/2026 17:00"),  # V(Paraguai x Franca)  x V(Canada x Marrocos)
    ("Jogo_98",  "Vencedor 93",  "Vencedor 94",  "un", "un", "10/07/2026 16:00"),  # V(Portugal x Espanha) x V(EUA x Belgica)
    ("Jogo_99",  "Vencedor 91",  "Vencedor 92",  "un", "un", "11/07/2026 18:00"),  # V(Brasil x Noruega)   x V(Mexico x Inglaterra)
    ("Jogo_100", "Vencedor 95",  "Vencedor 96",  "un", "un", "11/07/2026 22:00"),  # V(Argentina x Egito)  x V(Suica x Colombia)
    # Semifinais
    ("Jogo_101", "Vencedor 97",  "Vencedor 98",  "un", "un", "14/07/2026 16:00"),
    ("Jogo_102", "Vencedor 99",  "Vencedor 100", "un", "un", "15/07/2026 16:00"),
    # Disputa de 3o lugar — PERDEDORES das semifinais
    ("Jogo_103", "Perdedor 101", "Perdedor 102", "un", "un", "18/07/2026 18:00"),
    # Final
    ("Jogo_104", "Vencedor 101", "Vencedor 102", "un", "un", "19/07/2026 16:00"),
]

TODOS_CONFRONTOS = CONFRONTOS_OITAVAS + CONFRONTOS_PLACEHOLDER
IDS_AFETADOS = [c[0] for c in TODOS_CONFRONTOS]


def conectar():
    url = os.environ.get("DATABASE_URL")
    if url:
        import psycopg2
        if "sslmode=" not in url:
            url += "?sslmode=require"
        print(">> Banco alvo: PostgreSQL (PRODUCAO / Render)")
        return psycopg2.connect(url), True
    print(">> Banco alvo: SQLite local (bolao.db) — DATABASE_URL nao definida")
    conn = sqlite3.connect("bolao.db")
    conn.row_factory = sqlite3.Row
    return conn, False


def obter_cursor(conn, is_pg):
    if is_pg:
        from psycopg2.extras import DictCursor
        return conn.cursor(cursor_factory=DictCursor)
    return conn.cursor()


def coluna_existe(cursor, is_pg, tabela, coluna):
    if is_pg:
        cursor.execute(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = %s AND column_name = %s",
            (tabela, coluna),
        )
        return cursor.fetchone() is not None
    cursor.execute(f"PRAGMA table_info({tabela})")
    return any(r[1] == coluna for r in cursor.fetchall())


def buscar_estado_atual(cursor, is_pg, tem_penaltis):
    ph = ", ".join(["%s" if is_pg else "?"] * len(IDS_AFETADOS))
    col_pen = ", vencedor_penaltis" if tem_penaltis else ""
    cursor.execute(
        f"SELECT jogo_id, time1, time2, etapa, flag_code_time1, flag_code_time2, "
        f"       gols_time1_real, gols_time2_real, status, data_hora{col_pen} "
        f"FROM jogos WHERE jogo_id IN ({ph})",
        IDS_AFETADOS,
    )
    rows = [dict(r) for r in cursor.fetchall()]
    rows.sort(key=lambda r: int(r["jogo_id"].split("_")[1]))
    return rows


def buscar_palpites(cursor, is_pg):
    ph = ", ".join(["%s" if is_pg else "?"] * len(IDS_AFETADOS))
    cursor.execute(
        f"SELECT p.id, p.usuario_id, u.login, p.jogo_id, p.gols_time1, p.gols_time2 "
        f"FROM palpites p LEFT JOIN usuarios u ON u.id = p.usuario_id "
        f"WHERE p.jogo_id IN ({ph})",
        IDS_AFETADOS,
    )
    palpites = [dict(r) for r in cursor.fetchall()]
    palpites.sort(key=lambda p: (int(p["jogo_id"].split("_")[1]), str(p["login"])))
    return palpites


def salvar_backup(jogos_atuais, palpites_atuais):
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    nome = f"backup_chaveamento_oitavas_{ts}.json"
    with open(nome, "w", encoding="utf-8") as f:
        json.dump(
            {"jogos": jogos_atuais, "palpites": palpites_atuais},
            f, ensure_ascii=False, indent=2,
        )
    return nome


def mostrar_diff(jogos_atuais):
    mapa_atual = {j["jogo_id"]: j for j in jogos_atuais}
    print(f"\n{'ID':<10} {'ATUAL (time1 x time2)':<38} {'HORA ATUAL':<18} {'NOVO (time1 x time2)':<32} {'NOVA HORA'}")
    print("-" * 130)
    for jogo_id, t1, t2, f1, f2, dt in TODOS_CONFRONTOS:
        atual = mapa_atual.get(jogo_id)
        if not atual:
            print(f"{jogo_id:<10} *** NAO ENCONTRADO NO BANCO ***")
            continue
        atual_desc = f"{atual.get('time1', '?')} x {atual.get('time2', '?')}"
        atual_hora = str(atual.get("data_hora", "?"))
        status     = atual.get("status", "?")
        novo_desc  = f"{t1} x {t2}"
        mudou = (atual.get("time1") != t1 or atual.get("time2") != t2
                 or atual_hora != dt or status != "Pendente")
        marca = " <- ALTERA" if mudou else " (sem mudanca)"
        if status == "Encerrado":
            marca += " [ENCERRADO -> Pendente, gols zerados!]"
        elif status == "Em Andamento":
            marca += " [Em Andamento -> Pendente; reinicia sozinho no horario certo]"
        print(f"{jogo_id:<10} {atual_desc:<38} {atual_hora:<18} {novo_desc:<32} {dt}{marca}")


def relatorio_palpites(palpites, jogos_atuais):
    if not palpites:
        print("\nNenhum palpite existente nos jogos 89-104. Nada a decidir.")
        return
    mapa_atual = {j["jogo_id"]: j for j in jogos_atuais}
    print(f"\nATENCAO: {len(palpites)} palpite(s) ja registrados em jogos afetados.")
    print("Eles NAO serao alterados nem apagados — decida manualmente o que fazer:")
    print(f"\n{'JOGO':<10} {'CONFRONTO ATUAL':<38} {'USUARIO':<20} {'PALPITE'}")
    print("-" * 90)
    for p in palpites:
        atual = mapa_atual.get(p["jogo_id"], {})
        confronto = f"{atual.get('time1', '?')} x {atual.get('time2', '?')}"
        login = p["login"] or f"usuario_id={p['usuario_id']}"
        print(f"{p['jogo_id']:<10} {confronto:<38} {login:<20} {p['gols_time1']} x {p['gols_time2']}")


def aplicar(cursor, is_pg, tem_penaltis):
    ph = "%s" if is_pg else "?"
    set_pen = ", vencedor_penaltis = NULL" if tem_penaltis else ""
    for jogo_id, t1, t2, f1, f2, dt in TODOS_CONFRONTOS:
        cursor.execute(
            f"""
            UPDATE jogos
            SET time1 = {ph}, time2 = {ph},
                flag_code_time1 = {ph}, flag_code_time2 = {ph},
                data_hora = {ph},
                status = 'Pendente',
                gols_time1_real = NULL,
                gols_time2_real = NULL{set_pen}
            WHERE jogo_id = {ph}
            """,
            (t1, t2, f1, f2, dt, jogo_id),
        )
        print(f"  OK {jogo_id}: {t1} x {t2} | {dt}")


def main():
    dry_run = "--dry-run" in sys.argv

    print("=" * 70)
    print("  Correcao do chaveamento — Oitavas em diante (Jogos 89 a 104)")
    print(f"  Modo: {'DRY-RUN (nenhuma alteracao sera feita)' if dry_run else 'EXECUCAO REAL'}")
    print("=" * 70)

    conn, is_pg = conectar()
    cursor = obter_cursor(conn, is_pg)

    tem_penaltis = coluna_existe(cursor, is_pg, "jogos", "vencedor_penaltis")
    if not tem_penaltis:
        print("AVISO: coluna vencedor_penaltis nao existe neste banco — sera ignorada.")

    jogos_atuais    = buscar_estado_atual(cursor, is_pg, tem_penaltis)
    palpites_atuais = buscar_palpites(cursor, is_pg)

    print(f"\nEncontrado(s) {len(jogos_atuais)} de {len(IDS_AFETADOS)} jogo(s) esperados no banco.")

    mostrar_diff(jogos_atuais)
    relatorio_palpites(palpites_atuais, jogos_atuais)

    if dry_run:
        print("\n[DRY-RUN] Nada foi alterado. Rode sem --dry-run para aplicar.")
        cursor.close()
        conn.close()
        return

    arquivo_backup = salvar_backup(jogos_atuais, palpites_atuais)
    print(f"\nBackup salvo em: {arquivo_backup}")

    print("\nAplicando alteracoes...")
    aplicar(cursor, is_pg, tem_penaltis)
    conn.commit()
    print(f"\nConcluido. {len(TODOS_CONFRONTOS)} jogos corrigidos (Oitavas ate a Final).")
    print("Lembrete: faca o deploy do novo chaveamento.py ANTES de encerrar qualquer oitava,")
    print("senao o recalculo automatico antigo sobrescreve os confrontos corrigidos.")

    cursor.close()
    conn.close()


if __name__ == "__main__":
    main()
