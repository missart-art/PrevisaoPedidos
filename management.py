import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from database import setup_database # Assumindo que seu banco está aqui
from feedback import run_feedback_loop
from engine import run_projection_30_days

def render_fechamento_e_auditoria(conn):
    st.header("📝 Fechamento de Vendas (Ontem)")
    ontem = datetime.now().date() - timedelta(days=1)

    st.subheader("📁 Importar via Arquivo")
    arquivo_pedidos = st.file_uploader("Arraste o relatório de vendas", type=['csv', 'xlsx'])
    
    if arquivo_pedidos is not None:
        # Simulação de leitura para demonstração
        st.info(f"✅ Arquivo '{arquivo_pedidos.name}' detectado. O sistema está pronto para processar os dados.")
    
    st.divider()
    
    st.subheader("Fechamento Manual")
    with st.form("form_fechamento"):
        st.write(f"Registro para: {ontem}")
        df_meals = pd.read_sql_query("SELECT id, nome_prato FROM Meals", conn)
        inputs = {}
        
        # Cria campos de input dinamicamente
        for _, meal in df_meals.iterrows():
            inputs[meal['id']] = st.number_input(f"Vendas: {meal['nome_prato']}", min_value=0, step=1)
        
        
        if st.form_submit_button("Salvar"):
            cursor = conn.cursor()
            for m_id, qtd in inputs.items():
                cursor.execute("INSERT INTO Orders (data, meal_id, quantidade_pedida) VALUES (?, ?, ?)",
                             (ontem.strftime('%Y-%m-%d'), m_id, qtd))
            
            cursor.execute("UPDATE Daily_Context SET is_atypical = ? WHERE data = ?", 
                         (1 if is_atypical else 0, ontem.strftime('%Y-%m-%d')))
            conn.commit()
            
            msg = run_feedback_loop(conn)
            st.success(msg)

    st.divider()
    st.header("📈 Auditoria de Performance")
    df_audit = pd.read_sql_query("""
        SELECT data, SUM(quantidade_prevista) as Previsto, SUM(quantidade_real) as Real,
        ROUND(((SUM(quantidade_real) * 1.0 / SUM(quantidade_prevista)) - 1) * 100, 2) as Erro_Perc
        FROM Daily_Snapshots
        GROUP BY data ORDER BY data DESC LIMIT 10
    """, conn)

    df_audit['Previsto'] = df_audit['Previsto'].map('{:.0f}'.format)
    df_audit['Real'] = df_audit['Real'].map('{:.0f}'.format)
    df_audit['Erro_Perc'] = df_audit['Erro_Perc'].map('{:+.0f}%'.format)

    st.table(df_audit)

def render_overrides(conn):
    st.header("🕹️ Overrides Manuais")
    data_ov = st.date_input("Selecionar dia para Override", min_value=datetime.now().date())
    tipo_ov = st.selectbox("Forçar condição:", ["Nenhum", "Mar_Ruim", "Mar_Bom", "Feriado", "Ponte"])
    
    if st.button("Aplicar Intervenção"):
        cursor = conn.cursor()
        cursor.execute("UPDATE Daily_Context SET manual_override = ? WHERE data = ?", 
                     (tipo_ov if tipo_ov != "Nenhum" else None, data_ov.strftime('%Y-%m-%d')))
        conn.commit()
        run_projection_30_days(conn)
        st.success(f"Override aplicado para {data_ov}! Previsões recalculadas.")


def tela_adicionar_prato():
    st.header("🍴 Cadastro de Novo Prato")
    conn = setup_database()
    cursor = conn.cursor()

    # 1. Nome do Prato
    nome_prato = st.text_input("Nome do Prato", placeholder="Ex: Risoto de Camarão")

    # 2. Inicializa a lista de ingredientes no estado da sessão se não existir
    if 'lista_ingredientes' not in st.session_state:
        st.session_state.lista_ingredientes = [{"id": 0}] # Começa com um campo

    st.subheader("Ingredientes")
    
    # Busca ingredientes já cadastrados no banco para o selectbox
    cursor.execute("SELECT id, nome_ingrediente FROM Ingredients")
    opcoes_ingredientes = {nome: id for id, nome in cursor.fetchall()}
    nomes_disponiveis = list(opcoes_ingredientes.keys())

    if not nomes_disponiveis:
        st.warning("⚠️ Nenhum ingrediente encontrado no banco de dados.")
        st.info("Cadastre ingredientes primeiro ou execute o script de semente (seed).")
    
    # 3. Renderiza os campos de ingredientes dinamicamente
    ingredientes_selecionados = []
    
    for i, item in enumerate(st.session_state.lista_ingredientes):
        col1, col2 = st.columns([4, 1])
        
        with col1:
            sel = st.selectbox(f"Ingrediente {i+1}", nomes_disponiveis, key=f"ing_{i}")
            if sel is not None:
                ingredientes_selecionados.append(opcoes_ingredientes[sel])
            
        with col2:
            st.write("") # Alinhamento
            if st.button("🗑️", key=f"del_{i}"):
                st.session_state.lista_ingredientes.pop(i)
                st.rerun()

    # 4. Botões de Ação
    col_add, col_save = st.columns([1, 1])
    
    with col_add:
        if st.button("➕ Adicionar Ingrediente"):
            st.session_state.lista_ingredientes.append({"id": len(st.session_state.lista_ingredientes)})
            st.rerun()

    with col_save:
        if st.button("✅ Salvar Prato", type="primary"):
            if nome_prato and ingredientes_selecionados:
                salvar_no_banco(conn, nome_prato, ingredientes_selecionados)
                st.success(f"Prato '{nome_prato}' salvo com sucesso!")
                # Limpa a tela após salvar
                del st.session_state.lista_ingredientes
                st.rerun()
            else:
                st.error("Preencha o nome e pelo menos um ingrediente.")

def salvar_no_banco(conn, nome, lista_ids):
    cursor = conn.cursor()
    try:
        # Insere o prato e pega o ID gerado
        cursor.execute("INSERT INTO Meals (nome_prato) VALUES (?)", (nome,))
        meal_id = cursor.lastrowid
        
        # Relaciona cada ingrediente ao prato
        for ing_id in lista_ids:
            cursor.execute("INSERT INTO Meal_Ingredients (meal_id, ingredient_id) VALUES (?, ?)", 
                           (meal_id, ing_id))
        conn.commit()
    except Exception as e:
        st.error(f"Erro ao salvar: {e}")