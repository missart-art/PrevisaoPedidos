import sqlite3
from datetime import datetime, timedelta

def get_sea_score(onda, periodo, vento, direcao):
    if onda is None or periodo is None: return 0
    
    # 1. Energia da Onda (H² * T)
    score_onda = (onda ** 2) * periodo
    
    # 2. Impacto do Vento
    score_vento = (vento or 0) * 0.5
    
    # 3. Fator de Direção (Geografia de Ilhabela)
    # Sul é aproximadamente 180°. Quadrante Sul: 135° até 225°
    fator_direcao = 1.0
    try:
        dir_num = float(direcao)
        if 135 <= dir_num <= 225:
            fator_direcao = 1.5
    except (ValueError, TypeError):
        pass # Se não for número, ignora o fator
    
    return (score_onda + score_vento) * fator_direcao

def should_apply_mar_ruim(conn, data_str):
    cursor = conn.cursor()
    data_dt = datetime.strptime(data_str, '%Y-%m-%d')
    
    # 1. Verificação Física de Hoje (Agora com 4 parâmetros)
    cursor.execute("SELECT onda_altura, onda_periodo, vento_rajada, vento_direcao FROM Daily_Context WHERE data = ?", (data_str,))
    hoje = cursor.fetchone()

    if hoje is None or hoje[0] is None:
        return False

    # Calcula usando o novo modelo
    score_hoje = get_sea_score(hoje[0], hoje[1], hoje[2], hoje[3])
    fisico_ruim_hoje = score_hoje > 45 # Ajustamos o threshold para 45 devido ao novo peso do período

    # 2. Janela de Impacto (Olhar para frente)
    data_limite = (data_dt + timedelta(days=2)).strftime('%Y-%m-%d')
    cursor.execute("SELECT SUM(is_weekend + is_holiday) FROM Daily_Context WHERE data BETWEEN ? AND ?", (data_str, data_limite))
    tem_demanda_proxima = (cursor.fetchone()[0] or 0) > 0

    if fisico_ruim_hoje and tem_demanda_proxima:
        return True

    # 3. Efeito Arrastre (Sábado matou o Domingo)
    if data_dt.weekday() == 6:  # 6 é Domingo
        data_ontem = (data_dt - timedelta(days=1)).strftime('%Y-%m-%d')
        # PEGUE TODAS AS 4 VARIÁVEIS AQUI TAMBÉM:
        cursor.execute("SELECT onda_altura, onda_periodo, vento_rajada, vento_direcao FROM Daily_Context WHERE data = ?", (data_ontem,))
        ontem = cursor.fetchone()
        if ontem and ontem[0] is not None:
            # Passa os 4 parâmetros para o novo modelo
            if get_sea_score(ontem[0], ontem[1], ontem[2], ontem[3]) > 45:
                return True
                
    return False

def get_weighted_base(conn, meal_id, data_alvo):
    """Calcula a Base Ponderada: 40% Ano Anterior + 60% Últimas 2 Semanas."""
    cursor = conn.cursor()
    
    # 1. Média do mesmo dia no ano anterior (LY - Last Year)
    data_ly = (data_alvo - timedelta(days=365)).strftime('%Y-%m-%d')
    cursor.execute("SELECT AVG(quantidade_pedida) FROM Orders WHERE meal_id = ? AND data = ?", (meal_id, data_ly))
    res_ly = cursor.fetchone()[0]
    
    # 2. Média das últimas 2 semanas (L2W - Last 2 Weeks)
    data_limite_l2w = (datetime.now() - timedelta(days=14)).strftime('%Y-%m-%d')
    cursor.execute("SELECT AVG(quantidade_pedida) FROM Orders WHERE meal_id = ? AND data >= ?", (meal_id, data_limite_l2w))
    res_l2w = cursor.fetchone()[0] or 0 # Fallback se não houver vendas recentes

    # Lógica de decisão dos pesos
    if res_ly:
        base = (res_ly * 0.4) + (res_l2w * 0.6)
    else:
        base = res_l2w # Se não há histórico de 1 ano, usa 100% das últimas 2 semanas
        
    return base

def get_total_multiplier(conn, data_alvo):
    """Soma todos os multiplicadores de tags configurados para o contexto do dia."""
    cursor = conn.cursor()
    
    # Busca o contexto do dia (Etapa 2)
    cursor.execute("SELECT * FROM Daily_Context WHERE data = ?", (data_alvo.strftime('%Y-%m-%d'),))
    ctx = cursor.fetchone()
    if not ctx: return 1.0 # Sem contexto, multiplicador neutro

    override = ctx[-1] 
    if override:
        cursor.execute("SELECT valor_multiplicador FROM Tags_Config WHERE tag_nome = ?", (override,))
        res = cursor.fetchone()
        return res[0] if res else 1.0
    # ctx índices: 0:data, 1:onda, 2:periodo, 3:vento, 4:direcao, 5:temp, 6:condicao, 7:chuva, 8:fds, 9:feriado, 10:ponte
    multiplicador_final = 1.0
    
    # Exemplo de busca de multiplicadores na Tags_Config (implementando os filtros em cascata)
    tags_para_checar = []
    if (ctx[8] or 0) == 1: tags_para_checar.append('Final_de_Semana')
    if (ctx[9] or 0) == 1: tags_para_checar.append('Feriado')
    if (ctx[10] or 0) == 1: tags_para_checar.append('Ponte')
    # No engine.py, dentro de get_total_multiplier:
    chuva = ctx[7] or 0
    if chuva is not None: # SÓ APLICA SE TIVER DADO
        if chuva > 50: tags_para_checar.append('Chuva_Forte')
        elif chuva >= 20: tags_para_checar.append('Chuva_Leve')
    if should_apply_mar_ruim(conn, ctx[0]):
        tags_para_checar.append('Mar_Ruim')
    if (ctx[11] or 0) == 1: tags_para_checar.append('Inicio_Mes')
    if (ctx[12] or 0) == 1: tags_para_checar.append('Fim_Mes')
    
    if tags_para_checar:
        placeholders = ', '.join(['?'] * len(tags_para_checar))
        cursor.execute(f"SELECT valor_multiplicador FROM Tags_Config WHERE tag_nome IN ({placeholders})", tags_para_checar)
        for row in cursor.fetchall():
            multiplicador_final *= row[0]

    return multiplicador_final

def run_projection_30_days(conn):
    """Motor de Pre-calculation: Calcula e salva a previsão para os próximos 30 dias."""
    cursor = conn.cursor()
    hoje = datetime.now().date()
    
    # Limpa o cache antigo
    cursor.execute("DELETE FROM Forecast_Cache")
    
    # Busca todos os pratos cadastrados
    cursor.execute("SELECT id FROM Meals")
    meals = [m[0] for m in cursor.fetchall()]
    
    for i in range(30):
        data_alvo = hoje + timedelta(days=i)
        mult_dia = get_total_multiplier(conn, data_alvo)
        
        for meal_id in meals:
            base = get_weighted_base(conn, meal_id, data_alvo)
            previsao_final = round(base * mult_dia)
            
            cursor.execute('''
                INSERT INTO Forecast_Cache (data, meal_id, quantidade_final_calculada)
                VALUES (?, ?, ?)
            ''', (data_alvo.strftime('%Y-%m-%d'), meal_id, previsao_final))
            
    conn.commit()

def get_ingredient_explosion(conn, dias_horizonte=3):
    """
    Agrega a frequência de ingredientes para o horizonte selecionado.
    Output: Lista de (Ingrediente, Soma_de_Ocorrencias)
    """
    data_inicio = datetime.now().date().strftime('%Y-%m-%d')
    data_fim = (datetime.now().date() + timedelta(days=dias_horizonte)).strftime('%Y-%m-%d')
    
    query = '''
        SELECT 
            i.nome_ingrediente,
            SUM(f.quantidade_final_calculada) as total_frequencia
        FROM Forecast_Cache f
        JOIN Meal_Ingredients mi ON f.meal_id = mi.meal_id
        JOIN Ingredients i ON mi.ingredient_id = i.id
        WHERE f.data BETWEEN ? AND ?
        GROUP BY i.nome_ingrediente
        HAVING total_frequencia > 0
        ORDER BY total_frequencia DESC
    '''
    cursor = conn.cursor()
    return cursor.execute(query, (data_inicio, data_fim)).fetchall()

def get_tag_percentage(conn, tag_nome):
    if not tag_nome: 
        return None # Se não houver tag relevante, não mostra o delta
        
    cursor = conn.cursor()
    cursor.execute("SELECT valor_multiplicador FROM Tags_Config WHERE tag_nome = ?", (tag_nome,))
    res = cursor.fetchone()
    
    if res:
        mult = res[0]
        perc = (mult - 1) * 100
        
        # Se o impacto for 0%, retornamos None para o dashboard ficar limpo
        if round(perc) == 0: 
            return None
            
        # O sinal '+' no formatador força o + em positivos e o - em negativos
        return f"{perc:+.0f}%"
    
    return None