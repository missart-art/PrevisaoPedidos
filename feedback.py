import sqlite3
from datetime import datetime, timedelta

def close_daily_snapshot(conn, data_ontem):
    """
    Etapa 4.1: Consolida o Real vs. Previsto.
    Busca as vendas reais e atualiza o Snapshot do dia anterior.
    """
    cursor = conn.cursor()
    data_str = data_ontem.strftime('%Y-%m-%d')

    # Busca a soma de pedidos reais por prato no dia anterior
    cursor.execute('''
        SELECT meal_id, SUM(quantidade_pedida) 
        FROM Orders 
        WHERE data = ? 
        GROUP BY meal_id
    ''', (data_str,))
    vendas_reais = cursor.fetchall()

    if not vendas_reais:
        return False # Restaurante provavelmente fechado

    for meal_id, real in vendas_reais:
        # Atualiza a tabela de Snapshots com o que aconteceu de fato
        cursor.execute('''
            UPDATE Daily_Snapshots 
            SET quantidade_real = ? 
            WHERE data = ? AND meal_id = ?
        ''', (real, data_str, meal_id))
    
    conn.commit()
    return True

def apply_learning_loop(conn, data_ontem):
    """
    Etapa 4.2 e 4.3: Cálculo do Coeficiente e Atualização das Tags.
    """
    cursor = conn.cursor()
    data_str = data_ontem.strftime('%Y-%m-%d')

    # 1. Agregação total do dia para calcular o erro global
    cursor.execute('''
        SELECT SUM(quantidade_prevista), SUM(quantidade_real) 
        FROM Daily_Snapshots 
        WHERE data = ?
    ''', (data_str,))
    res = cursor.fetchone()
    
    previsto_total, real_total = res[0] or 0, res[1] or 0

    # Etapa 4.5: Tratamento de exceção (Real zero ou sem previsão)
    if real_total == 0 or previsto_total == 0:
        return "Aprendizado ignorado: Sem vendas ou sem previsão registrada."

    # Etapa 4.2: Coeficiente do Dia
    coeficiente_dia = real_total / previsto_total

    # 2. Identificar quais Tags estavam ativas ontem para aprender com elas
    cursor.execute("SELECT * FROM Daily_Context WHERE data = ?", (data_str,))
    ctx = cursor.fetchone()
    if not ctx: return "Sem contexto para aprender."

    # Mapeamento de índices do Daily_Context para nomes de Tags no Tags_Config
    tags_ativas = []
    if (ctx[8] or 0) == 1: tags_ativas.append('Final_de_Semana')
    if (ctx[9] or 0) == 1: tags_ativas.append('Feriado')
    if (ctx[10] or 0) == 1: tags_ativas.append('Ponte')
    if (ctx[7] or 0) > 50: tags_ativas.append('Chuva_Forte')
    if (ctx[1] or 0) > 2.0: tags_ativas.append('Mar_Ruim')

    # Etapa 4.3: Atualização Ponderada (80/20)
    for tag in tags_ativas:
        cursor.execute("SELECT valor_multiplicador FROM Tags_Config WHERE tag_nome = ?", (tag,))
        res_tag = cursor.fetchone()
        
        mult_antigo = res_tag[0] if res_tag else 1.0
        
        # Fórmula: Média ponderada para suavizar outliers
        novo_mult = (mult_antigo * 0.8) + (coeficiente_dia * 0.2)
        
        cursor.execute('''
            INSERT OR REPLACE INTO Tags_Config (tag_nome, valor_multiplicador) 
            VALUES (?, ?)
        ''', (tag, round(novo_mult, 4)))

    conn.commit()
    return f"Sucesso: Multiplicadores atualizados com Coeficiente {coeficiente_dia:.2f}"

def run_feedback_loop(conn):
    """Orquestrador do fechamento do dia anterior."""
    ontem = datetime.now().date() - timedelta(days=1)
    
    cursor = conn.cursor()
    cursor.execute("SELECT is_atypical FROM Daily_Context WHERE data = ?", (ontem.strftime('%Y-%m-%d'),))
    res = cursor.fetchone()
    if res and res[0] == 1:
        return "Dia Atípico: O sistema não aprendeu com este erro para evitar distorções."

    # 1. Consolida o real
    if close_daily_snapshot(conn, ontem):
        # 2. Se houve vendas, executa o aprendizado
        return apply_learning_loop(conn, ontem)
    else:
        return "Snapshot ignorado: Nenhuma venda registrada ontem."