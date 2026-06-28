MULTIPLICADORES_FASE = {
    'Dezesseis-avos de final':    1.5,
    'Oitavas de final':           2.0,
    'Quartas de final':           2.5,
    'Semifinais':                 3.5,
    'Disputa de terceiro lugar':  3.5,
    'Final':                      5.0,
}

def multiplicador_da_fase(etapa):
    if not etapa or etapa.startswith('Fase de Grupos'):
        return 1.0
    return MULTIPLICADORES_FASE.get(etapa, 1.0)


def calcular_pontos(gols_time1_real, gols_time2_real, gols_time1_palpite, gols_time2_palpite):
    pontos = 0
    
    # 1. Verificação de acerto em cheio (Placar Exato)
    if gols_time1_real == gols_time1_palpite and gols_time2_real == gols_time2_palpite:
        return 10  # Acerto completo não acumula com os outros bônus

    # 2. Verificação do Vencedor / Empate (5 pontos)
    vencedor_real = "time1" if gols_time1_real > gols_time2_real else "time2" if gols_time2_real > gols_time1_real else "empate"
    vencedor_palpite = "time1" if gols_time1_palpite > gols_time2_palpite else "time2" if gols_time2_palpite > gols_time1_palpite else "empate"
    
    if vencedor_real == vencedor_palpite:
        pontos += 5
        
        # 3. Bônus de Saldo de Gols (2 pontos) - Só ganha se já tiver acertado o vencedor/empate
        saldo_real = gols_time1_real - gols_time2_real
        saldo_palpite = gols_time1_palpite - gols_time2_palpite
        if saldo_real == saldo_palpite:
            pontos += 2

    # 4. Bônus de Gols de um dos times (1 ponto)
    if gols_time1_real == gols_time1_palpite or gols_time2_real == gols_time2_palpite:
        pontos += 1
        
    return pontos

