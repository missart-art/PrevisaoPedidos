import streamlit as st
import pandas as pd
import sqlite3
import calendar  # Adicionado import necessário
from datetime import datetime, date
import datetime as dt
from database import setup_database
from external import sync_external_data
from engine import run_projection_30_days, get_ingredient_explosion, should_apply_mar_ruim, get_tag_percentage
import management as mgt

# Configuração da Página
st.set_page_config(page_title="Previsão de Demanda - Ilha", layout="wide")
st.sidebar.success("💻 Login Autorizado")

def get_connection():
    conn = setup_database("sistema_previsao.db")
    conn.row_factory = sqlite3.Row  # Permite acessar colunas pelo nome[cite: 7]
    return conn

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
    st.title("📅 Dashboard de Previsão de Demanda")

    if st.button("🔄 Sincronizar Dados e Recalcular"):
        with st.spinner("Coletando clima/mar e gerando cache..."):
            conn = get_connection()
            sync_external_data(conn)
            run_projection_30_days(conn)
        st.success("Sistema atualizado!")
        st.rerun()

    conn = get_connection()
    df_cache = pd.read_sql_query("""
        SELECT f.data, SUM(f.quantidade_final_calculada) as total,
               c.temp_max, c.condicao, c.onda_altura, c.is_holiday
        FROM Forecast_Cache f
        LEFT JOIN Daily_Context c ON f.data = c.data
        GROUP BY f.data
    """, conn)

    if df_cache.empty:
        st.warning("⚠️ Clique em 'Sincronizar' para gerar as previsões.")

    # --- NAVEGAÇÃO DO MÊS ---
    if 'current_month' not in st.session_state:
        st.session_state.current_month = datetime.now().month
        st.session_state.current_year = datetime.now().year

    col_nav1, col_nav2 = st.columns([1, 2])
    with col_nav1:
        if st.button("⬅️ Mês Anterior"):
            st.session_state.current_month -= 1
            if st.session_state.current_month == 0:
                st.session_state.current_month = 12
                st.session_state.current_year -= 1
            st.rerun()
        if st.button("Próximo Mês ➡️"):
            st.session_state.current_month += 1
            if st.session_state.current_month == 13:
                st.session_state.current_month = 1
                st.session_state.current_year += 1
            st.rerun()

    with col_nav2:
        meses_br = ["", "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", 
                    "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"]
        st.markdown(f"<h2 style='text-align: center;'>{meses_br[st.session_state.current_month]} {st.session_state.current_year}</h2>", unsafe_allow_html=True)

    
    for week in month_days:
        cols = st.columns(7)
        for i, day in enumerate(week):
            if day == 0:
                cols[i].empty()
            else:
                data_obj = date(st.session_state.current_year, st.session_state.current_month, day)
                data_str = data_obj.strftime("%Y-%m-%d")
                nome_semana = dias_semana_pt[data_obj.weekday()]
                dados_dia = df_cache[df_cache['data'] == data_str]
                
                if not dados_dia.empty:
                    total = int(dados_dia.iloc[0]['total'])
                    cor = "🔴" if total > 100 else "🟡" if total > 50 else "🟢"
                    label = f"Dia {day}\n{nome_semana}\n{cor}"
                    disabled = False
                elif data_obj < hoje:
                    label = f"Dia {day}\n{nome_semana}\n🔘"
                    disabled = True 
                else:
                    label = f"Dia {day}\n{nome_semana}\n⚪"
                    disabled = False 

                with cols[i]:
                    if st.button(label, key=f"btn_{data_str}", use_container_width=True, disabled=disabled):
                        st.session_state['data_selecionada'] = data_str

# --- DETALHAMENTO DIÁRIO (ZOOM IN) ---
if 'data_selecionada' in st.session_state:
    st.divider()
    sel = st.session_state['data_selecionada']
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM Daily_Context WHERE data = ?", (sel,))
    ctx = cursor.fetchone()

    st.subheader(f"🔍 Painel de Controle: {datetime.strptime(sel, '%Y-%m-%d').strftime('%d/%m/%Y')}")
    
    # --- LINHA 1: INFORMAÇÕES ACUMULADAS ---
    m1, m2, m3 = st.columns(3)
    
    with m1:
        # Exibição de Tags Ativas[cite: 5]
        influencias = []
        if ctx and ctx['is_holiday']: influencias.append(('Feriado', '🚩 Feriado'))
        if ctx and ctx['is_weekend']: influencias.append(('Final_de_Semana', '📅 Fim de Semana'))
        
        tags_html = "".join([f'<p style="margin:0;">{label} <span style="color:#09ab3b;">({get_tag_percentage(conn, tid)})</span></p>' for tid, label in influencias])
        st.markdown(f'<div style="background:rgba(255,255,255,0.05);padding:10px;border-radius:5px;border-left:3px solid #ccc;">'
                    f'<p style="color:#888;font-size:0.8rem;">Influências</p>{tags_html if tags_html else "Dia Comum"}</div>', unsafe_allow_html=True)

    with m2:
        onda = ctx['onda_altura'] if ctx else 0
        status_mar = "Bravo" if onda > 1.5 else "Bom"
        st.markdown(f'<div style="background:rgba(255,255,255,0.05);padding:10px;border-radius:5px;border-left:3px solid #ccc;">'
                    f'<p style="color:#888;font-size:0.8rem;">Condição do Mar</p><p style="font-size:1.1rem;font-weight:600;">{status_mar}</p></div>', unsafe_allow_html=True)

    with m3:
        clima = ctx['condicao'] if ctx else "Sem Dados"
        st.markdown(f'<div style="background:rgba(255,255,255,0.05);padding:10px;border-radius:5px;border-left:3px solid #ccc;">'
                    f'<p style="color:#888;font-size:0.8rem;">Previsão Clima</p><p style="font-size:1.1rem;font-weight:600;">{clima}</p></div>', unsafe_allow_html=True)

    # --- LINHA 2: INTERVENÇÃO MANUAL ---
    st.write("---")
    c1, c2, c3 = st.columns(3)
    with c1:
        novo_mar = st.radio("Override Mar:", ["Automático", "Mar Bom", "Mar Ruim"], horizontal=True, key=f"ov_mar_{sel}")
    with c2:
        novo_clima = st.radio("Override Clima:", ["Automático", "Sol", "Chuva"], horizontal=True, key=f"ov_cli_{sel}")
    with c3:
        novo_feriado = st.radio("Override Feriado:", ["Automático", "Sim", "Não"], horizontal=True, key=f"ov_fer_{sel}")

    if st.button("✅ Aplicar Alterações e Recalcular"):
        # Salva as preferências manuais no banco[cite: 7]
        override = f"MAR:{novo_mar}|CLI:{novo_clima}|FER:{novo_feriado}"
        cursor.execute("UPDATE Daily_Context SET manual_override = ? WHERE data = ?", (override, sel))
        conn.commit()
        run_projection_30_days(conn)
        st.success("Cálculos atualizados para este dia!")
        st.rerun()

    # --- TABELAS DE DETALHE ---
    col_p, col_i = st.columns(2)
    with col_p:
        st.write("#### 🍽️ Pratos Previstos")
        df_pratos = pd.read_sql_query(f"SELECT m.nome_prato, f.quantidade_final_calculada as qtd FROM Forecast_Cache f JOIN Meals m ON f.meal_id = m.id WHERE f.data = '{sel}' ORDER BY qtd DESC", conn)
        st.dataframe(df_pratos, use_container_width=True)

    with col_i:
        st.write("#### 🧪 Explosão de Ingredientes")
        query_ing = f"SELECT i.nome_ingrediente, SUM(f.quantidade_final_calculada) as freq FROM Forecast_Cache f JOIN Meal_Ingredients mi ON f.meal_id = mi.meal_id JOIN Ingredients i ON mi.ingredient_id = i.id WHERE f.data = '{sel}' GROUP BY i.nome_ingrediente ORDER BY freq DESC"
        df_dia_ing = pd.read_sql_query(query_ing, conn)
        st.dataframe(df_dia_ing, use_container_width=True)

with tab2:
    mgt.render_fechamento_e_auditoria(conn)

with tab3:
    mgt.tela_adicionar_prato()
