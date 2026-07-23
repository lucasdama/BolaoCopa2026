# Dados do Bolão da Copa 2026

Snapshot final dos dados do bolão, exportado em **23/07/2026**, após o encerramento da Copa.

> **Segurança:** esta exportação é **sanitizada** — não contém senhas nem qualquer
> credencial. A tabela de usuários foi exportada apenas com os campos públicos
> (`id`, `login`, `admin`, `ativo`). Os dumps completos do banco (que contêm as
> senhas) ficam apenas localmente, na pasta `backups/`, que está no `.gitignore`.

## Campeão do bolão

🏆 **EdWorld** — 654,0 pontos

## Arquivos

| Arquivo | Descrição |
|---|---|
| `ranking_final.csv` | Classificação final dos participantes, com pontos calculados pela regra oficial. |
| `jogos.csv` | Os 104 jogos da Copa, com resultados reais, etapa, data e sede. |
| `palpites.csv` | Todos os 1.044 palpites dos participantes (referência: `usuario_id` → `usuarios.csv`, `jogo_id` → `jogos.csv`). |
| `usuarios.csv` | Participantes (sem senha). |

## Resultado da Copa

🥇 **Espanha** — campeã (venceu a Argentina na final por pênaltis, após 0 a 0).

## Regra de pontuação

Definida em `pontuacao.py`, aplicada por jogo e multiplicada conforme a fase:

- **10 pts** — placar exato (não acumula com os bônus abaixo).
- **5 pts** — acertou o vencedor / empate.
- **+2 pts** — acertou o saldo de gols (além do vencedor).
- **+1 pt** — acertou o número de gols de um dos times.

Multiplicadores por fase: dezesseis-avos 1,5× · oitavas 2,0× · quartas 2,5× ·
semifinais e disputa de 3º lugar 3,5× · final 5,0×. Fase de grupos: 1,0×.

O ranking é reconstruível a qualquer momento cruzando `palpites.csv` com `jogos.csv`
usando essa regra.
