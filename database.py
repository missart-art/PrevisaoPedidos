import sqlite3

def setup_database(db_name="sistema_previsao.db"):
    conn = sqlite3.connect(db_name)
    cursor = conn.cursor()

    # Habilitar suporte a chaves estrangeiras
    cursor.execute("PRAGMA foreign_keys = ON;")

    # --- 1. TABELAS DE CADASTRO (CARDÁPIO) ---
    
    # Refeições (Meals)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS Meals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome_prato TEXT NOT NULL UNIQUE
        )
    ''')

    # Ingredientes (Ingredients)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS Ingredients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome_ingrediente TEXT NOT NULL UNIQUE
        )
    ''')

    # Composição (Meal_Ingredients) - Relação Binária (Muitos-para-Muitos)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS Meal_Ingredients (
            meal_id INTEGER,
            ingredient_id INTEGER,
            PRIMARY KEY (meal_id, ingredient_id),
            FOREIGN KEY (meal_id) REFERENCES Meals(id) ON DELETE CASCADE,
            FOREIGN KEY (ingredient_id) REFERENCES Ingredients(id) ON DELETE CASCADE
        )
    ''')

    # --- 2. TABELAS DE MOVIMENTAÇÃO (HISTÓRICO E REALIDADE) ---

    # Pedidos (Orders) - Histórico para Média Ponderada
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS Orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            data DATE NOT NULL,
            meal_id INTEGER,
            quantidade_pedida INTEGER NOT NULL,
            FOREIGN KEY (meal_id) REFERENCES Meals(id)
        )
    ''')

    # Snapshots de Previsão (Daily_Snapshots) - Imutabilidade para Aprendizado
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS Daily_Snapshots (
            data DATE,
            meal_id INTEGER,
            quantidade_prevista INTEGER NOT NULL,
            quantidade_real INTEGER,
            PRIMARY KEY (data, meal_id),
            FOREIGN KEY (meal_id) REFERENCES Meals(id)
        )
    ''')

    # --- 3. TABELAS DE INTELIGÊNCIA (COEFICIENTES ADAPTATIVOS) ---

    # Tags e Multiplicadores (Tags_Config)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS Tags_Config (
            tag_nome TEXT PRIMARY KEY,
            valor_multiplicador REAL DEFAULT 1.0
        )
    ''')

    # Resumo de Previsão (Forecast_Cache) - Pré-calculado para 30 dias
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS Forecast_Cache (
            data DATE,
            meal_id INTEGER,
            quantidade_final_calculada INTEGER,
            PRIMARY KEY (data, meal_id),
            FOREIGN KEY (meal_id) REFERENCES Meals(id)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS Daily_Context (
            data DATE PRIMARY KEY,
            onda_altura REAL, onda_periodo REAL,
            vento_rajada REAL, vento_direcao TEXT,
            temp_max REAL, condicao TEXT, chuva_prob REAL,
            is_weekend INTEGER, is_holiday INTEGER, is_bridge INTEGER,
            is_start_of_month INTEGER, is_end_of_month INTEGER,
            is_atypical INTEGER DEFAULT 0,
            manual_override TEXT
        )
    ''')

    # --- ÍNDICES PARA PERFORMANCE ---
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_data ON Orders(data);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_forecast_data ON Forecast_Cache(data);")

    conn.commit()
    return conn

def query_explosao_ingredientes(conn, data_inicio, data_fim):
    """
    Executa a Lógica de Agregação (Ponto 4):
    Converte pratos previstos no período em soma de ocorrências de ingredientes.
    """
    query = '''
        SELECT 
            i.nome_ingrediente,
            SUM(f.quantidade_final_calculada) AS total_ocorrencias
        FROM Forecast_Cache f
        JOIN Meal_Ingredients mi ON f.meal_id = mi.meal_id
        JOIN Ingredients i ON mi.ingredient_id = i.id
        WHERE f.data BETWEEN ? AND ?
        GROUP BY i.nome_ingrediente
        ORDER BY total_ocorrencias DESC
    '''
    cursor = conn.cursor()
    return cursor.execute(query, (data_inicio, data_fim)).fetchall()

if __name__ == "__main__":
    connection = setup_database()
    print("Estrutura de dados (Etapa 1) criada com sucesso.")