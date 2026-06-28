import os

def atualizar_chaveamento_completo(cursor, is_postgres=False):
    """
    Motor central de chaveamento automático.
    Mapeia os times e calcula a árvore de mata-mata sem depender de uma tabela 'times'.
    """
    
    # 🔍 1. BUSCA JOGOS (Incluídas as colunas de flag_code para o mapa de bandeiras)
    cursor.execute("SELECT jogo_id, time1, time2, gols_time1_real, gols_time2_real, etapa, status, flag_code_time1, flag_code_time2, vencedor_penaltis FROM jogos")
    jogos_cruus = cursor.fetchall()

    jogos = []
    for j in jogos_cruus:
        if isinstance(j, dict):
            jogos.append(j)
        else:
            jogos.append({
                'jogo_id': j[0], 'time1': j[1], 'time2': j[2],
                'gols_time1_real': j[3], 'gols_time2_real': j[4],
                'etapa': j[5], 'status': j[6],
                'flag_code_time1': j[7], 'flag_code_time2': j[8],
                'vencedor_penaltis': j[9]
            })

    # 🗺️ 2. MAPEAMENTO FIXO DO RANKING FIFA (Para critérios de desempate)
    ranking_fifa_fixo = {
    'Argentina': 1,
    'Espanha': 2,
    'Franca': 3,
    'Inglaterra': 4,
    'Brasil': 5,
    'Portugal': 6,
    'Holanda': 7,
    'Belgica': 8,
    'Alemanha': 9,
    'Croacia': 10,
    'Italia': 11,
    'Marrocos': 12,
    'Uruguai': 13,
    'Colombia': 14,
    'Japao': 15,
    'Mexico': 16,
    'EUA': 17,
    'Senegal': 18,
    'Ira': 19,
    'Suica': 20,
    'Dinamarca': 21,
    'Austria': 22,
    'Coreia do Sul': 23,
    'Australia': 24,
    'Egito': 25,

    'Canada': 31,
    'Noruega': 38,
    'Paraguai': 48,
    'Costa do Marfim': 41,
    'Escocia': 44,
    'Turquia': 27,
    'Tunisia': 49,
    'Suecia': 29,
    'Arabia Saudita': 58,
    'Algeria': 36,
    'Panama': 33,
    'Gana': 76,
    'Jordania': 64,
    'Iraque': 59,
    'Catar': 55,
    'Nova Zelandia': 86,
    'Bosnia': 70,
    'Rep da Coreia': 23,
    'Rep Tcheca': 39,
    'Africa do Sul': 56,
    'Cabo Verde': 72,
    'Uzbequistao': 57,
    'Rep Dem Congo': 61,
    'Curacao': 91,
    'Haiti': 83,
}

    # 🗂️ 2.5 MAPEAMENTO FIXO DOS GRUPOS (Substitui a coluna group_letter que faltou)
    # Vincule aqui cada país ao seu respectivo grupo correto do seu arquivo times.csv
    grupos_times_fixo = {
        'Mexico': 'A',
        'Africa do Sul': 'A',
        'Rep da Coreia': 'A',
        'Rep Tcheca': 'A',

        'Canada': 'B',
        'Bosnia': 'B',
        'Catar': 'B',
        'Suica': 'B',

        'Brasil': 'C',
        'Marrocos': 'C',
        'Haiti': 'C',
        'Escocia': 'C',

        'EUA': 'D',
        'Paraguai': 'D',
        'Australia': 'D',
        'Turquia': 'D',

        'Alemanha': 'E',
        'Curacao': 'E',
        'Costa do Marfim': 'E',
        'Equador': 'E',

        'Holanda': 'F',
        'Japao': 'F',
        'Suecia': 'F',
        'Tunisia': 'F',

        'Belgica': 'G',
        'Egito': 'G',
        'Ira': 'G',
        'Nova Zelandia': 'G',

        'Espanha': 'H',
        'Cabo Verde': 'H',
        'Arabia Saudita': 'H',
        'Uruguai': 'H',

        'Franca': 'I',
        'Senegal': 'I',
        'Iraque': 'I',
        'Noruega': 'I',

        'Argentina': 'J',
        'Algeria': 'J',
        'Austria': 'J',
        'Jordania': 'J',

        'Portugal': 'K',
        'Rep Dem Congo': 'K',
        'Uzbequistao': 'K',
        'Colombia': 'K',

        'Inglaterra': 'L',
        'Croacia': 'L',
        'Gana': 'L',
        'Panama': 'L'
    }

    # 🧮 3. INICIALIZAR TABELA DE CLASSIFICAÇÃO DOS GRUPOS
    tabela = {}
    
    for j in jogos:
        if 'Fase de Grupos' in j['etapa']:
            for time in [j['time1'], j['time2']]:
                if time and time != "A definir" and time not in tabela:
                    # Busca o grupo diretamente no dicionário fixo acima
                    letra_grupo = grupos_times_fixo.get(time)
                    
                    tabela[time] = {
                        'nome': time, 
                        'grupo': letra_grupo, 
                        'pontos': 0,
                        'saldo': 0, 
                        'gols_pro': 0, 
                        'vitorias': 0, 
                        'ranking': ranking_fifa_fixo.get(time, 999)
                    }

    # ⚽ 4. CALCULAR PONTUAÇÃO DA FASE DE GRUPOS
    for j in jogos:
        if 'Fase de Grupos' in j['etapa'] and j['status'] == 'Encerrado' and j['gols_time1_real'] is not None:
            t1, t2 = j['time1'], j['time2']
            g1, g2 = int(j['gols_time1_real']), int(j['gols_time2_real'])
            
            if t1 not in tabela or t2 not in tabela: 
                continue
            
            tabela[t1]['gols_pro'] += g1
            tabela[t2]['gols_pro'] += g2
            tabela[t1]['saldo'] += (g1 - g2)
            tabela[t2]['saldo'] += (g2 - g1)

            if g1 > g2:
                tabela[t1]['pontos'] += 3
                tabela[t1]['vitorias'] += 1
            elif g2 > g1:
                tabela[t2]['pontos'] += 3
                tabela[t2]['vitorias'] += 1
            else:
                tabela[t1]['pontos'] += 1
                tabela[t2]['pontos'] += 1

    # Agrupa os resultados por letra de grupo
    grupos = {}
    for time_nome, dados in tabela.items():
        letra = dados['grupo']
        if letra:
            if letra not in grupos: 
                grupos[letra] = []
            grupos[letra].append(dados)

    # Ordenação oficial dos grupos
    grupos_classificados = {}
    for letra, times_grupo in grupos.items():
        def criterio_ordenacao(t):
            return (t['pontos'], t['saldo'], t['gols_pro'], -t['ranking'])
            
        ordenado = sorted(times_grupo, key=criterio_ordenacao, reverse=True)
        grupos_classificados[letra] = [t['nome'] for t in ordenado]
        
    # 🧩 5. RESOLVER REGRAS DOS MELHORES TERCEIROS COLOCADOS
    terceiros = []
    for letra, times_lista in grupos_classificados.items():
        if len(times_lista) >= 3:
            time_3 = times_lista[2]
            terceiros.append(tabela[time_3])
            
    terceiros_ordenados = sorted(terceiros, key=lambda x: (x['pontos'], x['saldo'], x['gols_pro'], -x['ranking']), reverse=True)
    oito_melhores = terceiros_ordenados[:8]
    mapa_3_colocados = {t['grupo']: t['nome'] for t in terceiros_ordenados}
    
    def alocar_terceiro_fallback(opcoes_validas, ja_alocados):
        for letra in opcoes_validas:
            if letra in mapa_3_colocados and mapa_3_colocados[letra] not in ja_alocados:
                return mapa_3_colocados[letra]
        return "A definir"

    alocados_3 = set()
    t3_74 = alocar_terceiro_fallback(['A', 'B', 'C', 'D', 'F'], alocados_3); alocados_3.add(t3_74)
    t3_77 = alocar_terceiro_fallback(['C', 'D', 'F', 'G', 'H'], alocados_3); alocados_3.add(t3_77)
    t3_79 = alocar_terceiro_fallback(['C', 'E', 'F', 'H', 'I'], alocados_3); alocados_3.add(t3_79)
    t3_80 = alocar_terceiro_fallback(['E', 'H', 'I', 'J', 'K'], alocados_3); alocados_3.add(t3_80)
    t3_81 = alocar_terceiro_fallback(['B', 'E', 'F', 'I', 'J'], alocados_3); alocados_3.add(t3_81)
    t3_82 = alocar_terceiro_fallback(['A', 'E', 'H', 'I', 'J'], alocados_3); alocados_3.add(t3_82)
    t3_85 = alocar_terceiro_fallback(['E', 'F', 'G', 'I', 'J'], alocados_3); alocados_3.add(t3_85)
    t3_87 = alocar_terceiro_fallback(['D', 'E', 'I', 'J', 'L'], alocados_3); alocados_3.add(t3_87)

    # 🌳 6. ESTRUTURAR NOVOS CONFRONTOS DO MATA-MATA
    novos_confrontos = {}

    def resolver_posicao_direta(sigla):
        if len(sigla) == 2 and sigla[0] in ['1', '2']:
            pos = int(sigla[0]) - 1
            letra_g = sigla[1]
            lista_times = grupos_classificados.get(letra_g, [])
            if len(lista_times) > pos:
                return lista_times[pos]
        return "A definir"

    # Fase 16-avos (Jogos 73 a 88): confrontos fixados manualmente conforme tabela oficial da FIFA.
    # NÃO recalcular automaticamente — os times já estão gravados no banco e não devem ser sobrescritos.

    # Auxiliar para buscar vencedores/perdedores das fases em cascata
    def obter_vencedor_ou_perdedor(id_partida, buscar_vencedor=True):
        match = next((item for item in jogos if item['jogo_id'] == id_partida), None)
        if not match or match['status'] != 'Encerrado':
            return f"Vencedor {id_partida.split('_')[1]}" if buscar_vencedor else f"Perdedor {id_partida.split('_')[1]}"

        g1 = int(match['gols_time1_real'] or 0)
        g2 = int(match['gols_time2_real'] or 0)

        if g1 > g2:
            return match['time1'] if buscar_vencedor else match['time2']
        elif g2 > g1:
            return match['time2'] if buscar_vencedor else match['time1']

        # Empate no placar normal: usar vencedor definido nos pênaltis
        vp = match.get('vencedor_penaltis')
        if buscar_vencedor:
            return vp if vp else match['time1']
        else:
            if vp:
                return match['time2'] if vp == match['time1'] else match['time1']
            return match['time2']

    estrutura_fluxo = {
        'Jogo_89': ('Jogo_74', 'Jogo_77'), 'Jogo_90': ('Jogo_73', 'Jogo_75'),
        'Jogo_91': ('Jogo_76', 'Jogo_78'), 'Jogo_92': ('Jogo_79', 'Jogo_80'),
        'Jogo_93': ('Jogo_83', 'Jogo_84'), 'Jogo_94': ('Jogo_81', 'Jogo_82'),
        'Jogo_95': ('Jogo_86', 'Jogo_88'), 'Jogo_96': ('Jogo_85', 'Jogo_87'),
        'Jogo_97': ('Jogo_89', 'Jogo_90'), 'Jogo_98': ('Jogo_93', 'Jogo_94'),
        'Jogo_99': ('Jogo_91', 'Jogo_92'), 'Jogo_100': ('Jogo_95', 'Jogo_96'),
        'Jogo_101': ('Jogo_97', 'Jogo_98'), 'Jogo_102': ('Jogo_99', 'Jogo_100'),
        'Jogo_103': ('Jogo_101', 'Jogo_102'), 
        'Jogo_104': ('Jogo_101', 'Jogo_102')
    }

    for j_id, (origem1, origem2) in estrutura_fluxo.items():
        if j_id == 'Jogo_103':
            t1 = obter_vencedor_ou_perdedor(origem1, buscar_vencedor=False)
            t2 = obter_vencedor_ou_perdedor(origem2, buscar_vencedor=False)
        else:
            t1 = obter_vencedor_ou_perdedor(origem1, buscar_vencedor=True)
            t2 = obter_vencedor_ou_perdedor(origem2, buscar_vencedor=True)
        novos_confrontos[j_id] = (t1, t2)

    # 💾 7. PERSISTÊNCIA NO BANCO & MAPEAMENTO DE BANDEIRAS DINÂMICAS
    placeholder = '%s' if is_postgres else '?'
    query_update = f'''
        UPDATE jogos 
        SET time1 = {placeholder}, time2 = {placeholder}, flag_code_time1 = {placeholder}, flag_code_time2 = {placeholder}
        WHERE jogo_id = {placeholder} AND status = 'Pendente'
    '''

    # Criamos um dicionário de bandeiras baseado no que já existe populado na tabela jogos
    mapa_bandeiras = {}
    for j in jogos:
        if j['time1'] and j['flag_code_time1']: 
            mapa_bandeiras[j['time1']] = j['flag_code_time1']
        if j['time2'] and j['flag_code_time2']: 
            mapa_bandeiras[j['time2']] = j['flag_code_time2']

    for j_id, (time1, time2) in novos_confrontos.items():
        f1 = mapa_bandeiras.get(time1, 'un') if time1 != "A definir" and "Vencedor" not in time1 and "Perdedor" not in time1 else 'un'
        f2 = mapa_bandeiras.get(time2, 'un') if time2 != "A definir" and "Vencedor" not in time2 and "Perdedor" not in time2 else 'un'
        
        cursor.execute(query_update, (time1, time2, f1, f2, j_id))