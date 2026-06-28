"""
Corrige os confrontos da fase dezesseis-avos no banco de PRODUÇÃO (PostgreSQL/Render).

Uso:
    # Apenas mostra o que seria alterado (sem tocar nada):
    DATABASE_URL="<sua-string>" python corrigir_dezesseis_avos_prod.py --dry-run

    # Aplica a correção (gera backup antes):
    DATABASE_URL="<sua-string>" python corrigir_dezesseis_avos_prod.py

A variável DATABASE_URL deve ser definida na linha de comando — nunca hardcoded aqui.
"""

import os
import sys
import json
import datetime
import psycopg2
from psycopg2.extras import DictCursor

# ─── Confrontos reais definidos pela FIFA ────────────────────────────────────
CONFRONTOS_REAIS = [
    # (jogo_id, time1, time2, flag1, flag2, data_hora)
    ("Jogo_73", "Africa do Sul", "Canada",        "ZA", "CA", "28/06/2026 16:00"),
    ("Jogo_74", "Brasil",        "Japao",          "BR", "JP", "29/06/2026 14:00"),
    ("Jogo_75", "Alemanha",      "Paraguai",       "DE", "PY", "29/06/2026 17:30"),
    ("Jogo_76", "Holanda",       "Marrocos",       "NL", "MC", "29/06/2026 22:00"),
    ("Jogo_77", "Costa do Marfim","Noruega",       "CI", "NO", "30/06/2026 14:00"),
    ("Jogo_78", "Franca",        "Suecia",         "FR", "SE", "30/06/2026 18:00"),
    ("Jogo_79", "Mexico",        "Equador",        "MX", "EC", "30/06/2026 22:00"),
    ("Jogo_80", "Inglaterra",    "Rep Dem Congo",  "GB", "CD", "01/07/2026 13:00"),
    ("Jogo_81", "Belgica",       "Senegal",        "BE", "SN", "01/07/2026 17:00"),
    ("Jogo_82", "EUA",           "Bosnia",         "US", "BA", "01/07/2026 21:00"),
    ("Jogo_83", "Espanha",       "Austria",        "ES", "AT", "02/07/2026 16:00"),
    ("Jogo_84", "Portugal",      "Croacia",        "PT", "HR", "02/07/2026 20:00"),
    ("Jogo_85", "Suica",         "Algeria",        "CH", "DZ", "03/07/2026 00:00"),
    ("Jogo_86", "Australia",     "Egito",          "AU", "EG", "03/07/2026 15:00"),
    ("Jogo_87", "Argentina",     "Cabo Verde",     "AR", "CV", "03/07/2026 19:00"),
    ("Jogo_88", "Colombia",      "Gana",           "CO", "GH", "03/07/2026 22:30"),
]

IDS_DEZESSEIS = [c[0] for c in CONFRONTOS_REAIS]


def conectar():
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("ERRO: variável DATABASE_URL não definida.")
        print("  Defina-a antes de rodar: DATABASE_URL='...' python corrigir_dezesseis_avos_prod.py")
        sys.exit(1)
    if "sslmode=" not in url:
        url += "?sslmode=require"
    return psycopg2.connect(url)


def buscar_estado_atual(cursor):
    ids = IDS_DEZESSEIS
    cursor.execute(
        "SELECT jogo_id, time1, time2, flag_code_time1, flag_code_time2, "
        "       gols_time1_real, gols_time2_real, status, data_hora "
        "FROM jogos WHERE jogo_id = ANY(%s) ORDER BY jogo_id",
        (ids,),
    )
    return [dict(r) for r in cursor.fetchall()]


def buscar_palpites(cursor):
    cursor.execute(
        "SELECT p.id, p.usuario_id, p.jogo_id, p.gols_time1, p.gols_time2 "
        "FROM palpites p WHERE p.jogo_id = ANY(%s)",
        (IDS_DEZESSEIS,),
    )
    return [dict(r) for r in cursor.fetchall()]


def salvar_backup(jogos_atuais, palpites_atuais):
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    nome = f"backup_dezesseis_avos_{ts}.json"
    with open(nome, "w", encoding="utf-8") as f:
        json.dump({"jogos": jogos_atuais, "palpites": palpites_atuais}, f, ensure_ascii=False, indent=2)
    return nome


def mostrar_diff(jogos_atuais):
    mapa_atual = {j["jogo_id"]: j for j in jogos_atuais}
    print(f"\n{'ID':<10} {'ATUAL (time1 x time2)':<35} {'HORA ATUAL':<20} {'NOVO (time1 x time2)':<35} {'NOVA HORA'}")
    print("-" * 130)
    for jogo_id, t1, t2, f1, f2, dt in CONFRONTOS_REAIS:
        atual = mapa_atual.get(jogo_id, {})
        atual_desc  = f"{atual.get('time1','?')} x {atual.get('time2','?')}"
        atual_hora  = atual.get("data_hora", "?")
        status      = atual.get("status", "?")
        novo_desc   = f"{t1} x {t2}"
        mudou       = (atual.get("time1") != t1 or atual.get("time2") != t2
                       or atual.get("data_hora") != dt or status == "Encerrado")
        marca = " ← ALTERA" if mudou else " (sem mudança)"
        if status == "Encerrado":
            marca += " [ENCERRADO → Pendente, gols zerados]"
        print(f"{jogo_id:<10} {atual_desc:<35} {atual_hora:<20} {novo_desc:<35} {dt}{marca}")


def aplicar(cursor):
    for jogo_id, t1, t2, f1, f2, dt in CONFRONTOS_REAIS:
        cursor.execute(
            """
            UPDATE jogos
            SET time1 = %s, time2 = %s,
                flag_code_time1 = %s, flag_code_time2 = %s,
                data_hora = %s,
                status = 'Pendente',
                gols_time1_real = NULL,
                gols_time2_real = NULL
            WHERE jogo_id = %s
            """,
            (t1, t2, f1, f2, dt, jogo_id),
        )
        print(f"  ✓ {jogo_id}: {t1} x {t2} | {dt}")


def main():
    dry_run = "--dry-run" in sys.argv

    print("=" * 60)
    print("  Correção dezesseis-avos — banco de PRODUÇÃO")
    print(f"  Modo: {'DRY-RUN (nenhuma alteração será feita)' if dry_run else 'EXECUÇÃO REAL'}")
    print("=" * 60)

    conn = conectar()
    cursor = conn.cursor(cursor_factory=DictCursor)

    jogos_atuais  = buscar_estado_atual(cursor)
    palpites_atuais = buscar_palpites(cursor)

    print(f"\nEncontrado(s) {len(jogos_atuais)} jogo(s) de dezesseis-avos no banco.")
    print(f"Palpites associados a esses jogos: {len(palpites_atuais)}")

    if palpites_atuais:
        print("\nATENÇÃO: existem palpites associados — eles NÃO serão alterados por este script.")

    mostrar_diff(jogos_atuais)

    if dry_run:
        print("\n[DRY-RUN] Nada foi alterado. Rode sem --dry-run para aplicar.")
        cursor.close()
        conn.close()
        return

    # Backup antes de alterar
    arquivo_backup = salvar_backup(jogos_atuais, palpites_atuais)
    print(f"\nBackup salvo em: {arquivo_backup}")

    print("\nAplicando alterações...")
    aplicar(cursor)
    conn.commit()
    print("\n✅ Concluído. Todos os 16 jogos foram corrigidos no banco de produção.")

    cursor.close()
    conn.close()


if __name__ == "__main__":
    main()
