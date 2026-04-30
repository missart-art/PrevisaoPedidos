import streamlit as st
import pandas as pd
import sqlite3
from datetime import datetime, timedelta
from database import setup_database
from external import sync_external_data
from engine import run_projection_30_days, get_ingredient_explosion, should_apply_mar_ruim
import calendar
import management as mgt
from seguranca import interface_login

# Configuração da Página
st.set_page_config(page_title="Previsão de Demanda - Ilha", layout="wide")

interface_login()

st.sidebar.success("💻 Login Autorizado")


def get_connection():
    return setup_database("sistema_previsao.db")

def format_mar(altura):
    if altura is None: return "⚪"
    if altura < 1.0: return "🟢 (Bom)"
    if altura < 2.0: return "🟡 (Médio)"
    return "🔴 (Bravo)"

# --- SIDEBAR: EXPLOSÃO DE COMPRAS ---
st.sidebar.header("Ver demanda futura")
horizonte = st.sidebar.radio("Quantos dias:", [3, 7, 15, 30], format_func=lambda x: f"Próximos {x} dias")

if st.sidebar.button("Gerar Lista de Explosão"):
    conn = get_connection()
    lista_ingredientes = get_ingredient_explosion(conn, horizonte)
    
    st.sidebar.subheader(f"Insumos - {horizonte} dias")
    df_ing = pd.DataFrame(lista_ingredientes, columns=["Ingrediente", "Ocorrências"])
    st.sidebar.table(df_ing)

tab1, tab2, tab3 = st.tabs(["📅 Calendário", "📊 Auditoria & Fechamento", "🍽️ Adicionar Pratos"])

with tab1:
    # --- DASHBOARD PRINCIPAL ---
    st.title("📅 Dashboard de Previsão de Demanda")

    if st.button("🔄 Sincronizar Dados e Recalcular"):
        with st.spinner("Coletando clima/mar e gerando cache..."):
            conn = get_connection()
            sync_external_data(conn)
            run_projection_30_days(conn)
        st.success("Sistema atualizado!")

    # Carregar Dados do Cache
    conn = get_connection()
    df_cache = pd.read_sql_query("""
        SELECT f.data, SUM(f.quantidade_final_calculada) as total,
            c.temp_max, c.condicao, c.onda_altura, c.is_holiday
        FROM Forecast_Cache f
        LEFT JOIN Daily_Context c ON f.data = c.data
        GROUP BY f.data
    """, conn)

    # --- Adicione isso logo após carregar o df_cache no app.py ---
    if df_cache.empty:
        st.warning("⚠️ O calendário está vazio porque não há previsões calculadas. "
                "Certifique-se de que existem pratos cadastrados no cardápio e clique em 'Sincronizar'.")

    # --- CONTROLE DE NAVEGAÇÃO DO MÊS ---
    # --- CONTROLE DE NAVEGAÇÃO DO MÊS ---
    if 'current_month' not in st.session_state:
        st.session_state.current_month = datetime.now().month
        st.session_state.current_year = datetime.now().year

    col_nav1, col_nav2, col_nav3 = st.columns([1, 2, 1])

    with col_nav1:
        if st.button("⬅️ Mês Anterior"):
            st.session_state.current_month -= 1
            if st.session_state.current_month == 0:
                st.session_state.current_month = 12
                st.session_state.current_year -= 1
            st.rerun() # <--- ADICIONE ISSO

    with col_nav2:
        meses_br = ["", "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", 
                "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"]
    
        mes_nome = meses_br[st.session_state.current_month]
        st.markdown(f"<h2 style='text-align: center;'>{mes_nome} {st.session_state.current_year}</h2>", unsafe_allow_html=True)
    
    with col_nav3:
        if st.button("Próximo Mês ➡️"):
            st.session_state.current_month += 1
            if st.session_state.current_month == 13:
                st.session_state.current_month = 1
                st.session_state.current_year += 1
            st.rerun() # <--- ADICIONE ISSO

    # --- MONTAGEM DA GRADE REAL ---
    dias_semana = ["Dom", "Seg", "Ter", "Qua", "Qui", "Sex", "Sáb"]
    cols_header = st.columns(7)
    for i, dia in enumerate(dias_semana):
        cols_header[i].markdown(f"**{dia}**")

    # Configura o calendário para começar no Domingo (igual à sua foto)
    cal = calendar.Calendar(firstweekday=6)
    month_days = cal.monthdayscalendar(st.session_state.current_year, st.session_state.current_month)

    for week in month_days:
        cols = st.columns(7)
        for i, day in enumerate(week):
            if day == 0:
                cols[i].write("") # Espaço vazio para dias fora do mês
            else:
                # Formata a data para buscar no banco
                data_atual = f"{st.session_state.current_year}-{st.session_state.current_month:02d}-{day:02d}"
                
                # Busca dados específicos deste dia no DataFrame df_cache
                dados_dia = df_cache[df_cache['data'] == data_atual]
                
                if not dados_dia.empty:
                    total = int(dados_dia.iloc[0]['total'])
                    cor = "🔴" if total > 100 else "🟡" if total > 50 else "🟢"
                    
                    with cols[i]:
                        if st.button(f"{day}\n{cor}", key=f"btn_{data_atual}", use_container_width=True):
                            st.session_state['data_selecionada'] = data_atual
                else:
                    cols[i].write(f"{day}") # Dia sem previsão (passado ou futuro distante)

    # --- DETALHAMENTO DIÁRIO (ZOOM IN) ---
if 'data_selecionada' in st.session_state:
    st.divider()
    sel = st.session_state['data_selecionada']
    
    # Busca dados completos do dia para os Toggles
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM Daily_Context WHERE data = ?", (sel,))
    ctx = cursor.fetchone()

    st.subheader(f"🔍 Painel de Controle: {datetime.strptime(sel, '%Y-%m-%d').strftime('%d/%m/%Y')}")
    # --- LINHA 1: STATUS E PORCENTAGENS (INFO) ---
    m1, m2, m3, m4 = st.columns(4)
    
    ov_mar = st.session_state.get(f"mar_{sel}", "Automático")
    ov_clima = st.session_state.get(f"clima_{sel}", "Automático")
    ov_feriado = st.session_state.get(f"feriado_{sel}", "Automático")

    with m1:
        # 1. Pegamos todas as variáveis do contexto
        is_holiday = ctx[9] if ctx else 0
        is_weekend = ctx[8] if ctx else 0
        is_bridge  = ctx[10] if ctx else 0
        is_start   = ctx[11] if ctx else 0
        is_end     = ctx[12] if ctx else 0

        # 2. Criamos uma lista de todas as tags ativas no dia
        influencias = []
        
        # Checagem de Feriado (Manual ou Automática)
        if ov_feriado == "Sim": 
            influencias.append(('Feriado', '🚩 Feriado (Manual)'))
        elif is_holiday: 
            influencias.append(('Feriado', '🚩 Feriado'))
        
        # Outras influências automáticas
        if is_bridge: influencias.append(('Ponte', '🌉 Ponte'))
        if is_start:  influencias.append(('Inicio_Mes', '💰 Início de Mês'))
        if is_end:    influencias.append(('Fim_Mes', '📉 Fim de Mês'))
        
        # FDS só aparece se não for feriado (para não poluir)
        if is_weekend and not is_holiday: 
            influencias.append(('Final_de_Semana', '📅 Fim de Semana'))
        
        # Se não houver nada, é um dia comum
        if not influencias:
            influencias.append((None, 'Dia de Semana'))

        # 3. Geramos o HTML para cada influência encontrada
        tags_html = ""
        for tag_id, label in influencias:
            p = get_tag_percentage(conn, tag_id)
            delta = ""
            if p:
                cor = "#09ab3b" if "+" in p else "#ff4b4b"
                # Colocamos a porcentagem pequena ao lado do nome
                delta = f' <span style="color: {cor}; font-size: 0.85rem; font-weight: normal;">({p})</span>'
            
            tags_html += f'<p style="margin: 0; font-size: 1.0rem; font-weight: 600; line-height: 1.4;">{label}{delta}</p>'

        st.markdown(f"""
            <div style="background-color: rgba(255, 255, 255, 0.05); padding: 10px; border-radius: 5px; border-left: 3px solid #ccc; min-height: 100px;">
                <p style="margin: 0 0 5px 0; font-size: 0.8rem; color: #888;">Influências Acumuladas</p>
                {tags_html}
            </div>
        """, unsafe_allow_html=True)

    with m2:

        if ov_mar != "Automático":
            mar_status = "Bravo (Manual)" if ov_mar == "Mar Ruim" else "Bom (Manual)"
            impacto_mar = (ov_mar == "Mar Ruim")
        else:
            onda_h = ctx[1] if ctx else None
            vento_v = ctx[3] if ctx else None
            if onda_h is None: 
                mar_status, impacto_mar = "Sem dados", False
            else:
                mar_status = "Bravo" if (onda_h * 10 + vento_v) > 35 else "Bom"
                impacto_mar = should_apply_mar_ruim(conn, sel)

        p_mar = get_tag_percentage(conn, 'Mar Ruim' if impacto_mar else None)
        delta_mar = f'<span style="color: #ff4b4b; font-size: 0.9rem;">↓ {p_mar}</span>' if p_mar else ""

        st.markdown(f'<div style="background-color: rgba(255, 255, 255, 0.05); padding: 10px; border-radius: 5px; border-left: 3px solid #ccc; min-height: 100px;">'
                    f'<p style="margin: 0; font-size: 0.8rem; color: #888;">Condição do Mar</p>'
                    f'<p style="margin: 0; font-size: 1.1rem; font-weight: 600;">{mar_status}</p>{delta_mar}</div>', unsafe_allow_html=True)

    #with m3:

     #   temp_val = ctx[5] if ctx else 'Sem Dados'

      #  st.markdown(f'<div style="background-color: rgba(255, 255, 255, 0.05); padding: 10px; border-radius: 5px; border-left: 3px solid #ccc; min-height: 100px;">'
       #             f'<p style="margin: 0; font-size: 0.8rem; color: #888;">Temperatura Máx</p>'
        #            f'<p style="margin: 0; font-size: 1.1rem; font-weight: 600;">{temp_val}</p></div>', unsafe_allow_html=True)
        
    with m3:

        if ov_clima != "Automático":
            clima_exibicao = f"{ov_clima} (Manual)"
            tag_clima = 'Chuva_Forte' if ov_clima == "Chuva" else None
        else:
            clima_exibicao = ctx[6] if ctx and ctx[6] else "Sem dados"
            prob_chuva = ctx[7] if ctx else None
            tag_clima = 'Chuva_Forte' if (prob_chuva or 0) > 50 else ('Chuva_Leve' if (prob_chuva or 0) >= 20 else None)

        p_chuva = get_tag_percentage(conn, tag_clima)
        delta_clima = f'<span style="color: #ff4b4b; font-size: 0.9rem;">↓ {p_chuva}</span>' if p_chuva else ""

        st.markdown(f'<div style="background-color: rgba(255, 255, 255, 0.05); padding: 10px; border-radius: 5px; border-left: 3px solid #ccc; min-height: 100px;">'
                    f'<p style="margin: 0; font-size: 0.8rem; color: #888;">Clima</p>'
                    f'<p style="margin: 0; font-size: 1.1rem; font-weight: 600;">{clima_exibicao}</p>{delta_clima}</div>', unsafe_allow_html=True)

    # --- LINHA 2: TOGGLES DE INTERVENÇÃO (MUDANÇA EM TEMPO REAL) ---
    c1, c2, c3 = st.columns(3)

    with c1:
        # Toggle de Mar
        novo_mar = st.radio("Alterar Mar:", ["Automático", "Mar Bom", "Mar Ruim"], 
                            index=0, horizontal=True, key=f"mar_{sel}")
    
    
    
    if st.button("✅ Aplicar e Recalcular"):
        # Lógica para salvar no banco (Manual Override)
        # Vamos concatenar os overrides se houver mais de um, ou tratar no engine
        override_list = []
        if novo_mar != "Automático": override_list.append(novo_mar)
        
        # Salvamos o override principal (o motor atual lê apenas um, ideal expandir o motor depois)
        final_override = override_list[0] if override_list else None
        
        cursor.execute("UPDATE Daily_Context SET manual_override = ? WHERE data = ?", (final_override, sel))
        # Se for feriado manual, atualizamos a coluna is_holiday também para o motor ler
            
        conn.commit()
        run_projection_30_days(conn)
        st.success("Configurações aplicadas!")
        st.rerun()
    # --- TABELAS DE EXPLOSÃO (PRATOS E INGREDIENTES) ---
    col_p, col_i = st.columns(2)
    
    with col_p:
        st.write("#### 🍽️ Pratos")
        df_pratos = pd.read_sql_query(f"SELECT m.nome_prato, f.quantidade_final_calculada as qtd FROM Forecast_Cache f JOIN Meals m ON f.meal_id = m.id WHERE f.data = '{sel}' ORDER BY qtd DESC", conn)
        st.dataframe(df_pratos, use_container_width=True)

    with col_i:
        st.write("#### 🧪 Ingredientes")
        query_ing = f"SELECT i.nome_ingrediente, SUM(f.quantidade_final_calculada) as freq FROM Forecast_Cache f JOIN Meal_Ingredients mi ON f.meal_id = mi.meal_id JOIN Ingredients i ON mi.ingredient_id = i.id WHERE f.data = '{sel}' GROUP BY i.nome_ingrediente ORDER BY freq DESC"
        df_dia_ing = pd.read_sql_query(query_ing, conn)
        st.dataframe(df_dia_ing, use_container_width=True)
            # Justificativa de Cálculo
       
with tab2:
    # Apenas chama a função modularizada
    mgt.render_fechamento_e_auditoria(conn)

with tab3:

    mgt.tela_adicionar_prato()