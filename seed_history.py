import sqlite3
import random
from datetime import datetime, timedelta
from database import setup_database
from external import get_calendar_tags

def seed_everything():
    # Conecta ao banco (certifique-se de que o app.py use este mesmo nome)
    conn = setup_database("sistema_previsao.db")
    cursor = conn.cursor()

    print("🧹 Faxina total: Resetando banco, contadores e estrutura...")
    cursor.execute("PRAGMA foreign_keys = OFF;")
    
    # Remove a tabela de contexto para garantir a estrutura de 15 colunas
    cursor.execute("DROP TABLE IF EXISTS Daily_Context")
    
    # Limpa todas as tabelas e reseta os contadores de ID (AUTOINCREMENT)
    tables = ["Orders", "Meals", "Ingredients", "Meal_Ingredients", "Tags_Config", "Daily_Snapshots", "Forecast_Cache"]
    for table in tables:
        cursor.execute(f"DELETE FROM {table}")
        cursor.execute(f"DELETE FROM sqlite_sequence WHERE name='{table}'")
    
    # Recria a Daily_Context com a estrutura oficial
    cursor.execute('''
        CREATE TABLE Daily_Context (
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
    cursor.execute("PRAGMA foreign_keys = ON;")

    # --- 1. CADASTRO DE INGREDIENTES (Mapeamento Dinâmico) ---
    print("🍳 Cadastrando insumos e pratos...")
    insumos_nomes = ["Peixe Branco", "Camarão", "Cebola", "Arroz", "Tomate", "Leite de Coco", "Azeite de Dendê", "Batata"]
    ing_map = {}
    for nome in insumos_nomes:
        cursor.execute("INSERT INTO Ingredients (nome_ingrediente) VALUES (?)", (nome,))
        ing_map[nome] = cursor.lastrowid # Pega o ID real que o banco gerou

    # --- 2. CADASTRO DE PRATOS ---
    pratos_def = [
        ("Muqueca Capixaba", ["Peixe Branco", "Cebola", "Tomate", "Leite de Coco", "Azeite de Dendê"]),
        ("Risoto de Camarão", ["Camarão", "Cebola", "Arroz"]),
        ("Peixe com Batatas", ["Peixe Branco", "Batata", "Cebola"]),
        ("Arroz de Marisco", ["Camarão", "Arroz", "Cebola", "Tomate"])
    ]
    
    for nome_prato, lista_ing in pratos_def:
        cursor.execute("INSERT INTO Meals (nome_prato) VALUES (?)", (nome_prato,))
        m_id = cursor.lastrowid
        for n_ing in lista_ing:
            cursor.execute("INSERT INTO Meal_Ingredients VALUES (?, ?)", (m_id, ing_map[n_ing]))

    # --- 3. CONFIGURAÇÃO DE TAGS (Valores iniciais propositalmente imprecisos) ---
    tags_iniciais = [
        ('Final_de_Semana', 1.2), ('Feriado', 1.8), ('Ponte', 1.4),
        ('Chuva_Forte', 0.9), ('Mar_Ruim', 0.8), 
        ('Inicio_Mes', 1.1), ('Fim_Mes', 0.9)
    ]
    cursor.executemany("INSERT INTO Tags_Config VALUES (?, ?)", tags_iniciais)

    # --- 4. GERAÇÃO DE HISTÓRICO COM VARIABILIDADE REAL ---
# --- 4. GERAÇÃO DE HISTÓRICO COM VARIABILIDADE REAL ---
    print("🌱 Gerando histórico com física real (365 dias)...")
    cursor.execute("SELECT id FROM Meals")
    ids_reais = [row[0] for row in cursor.fetchall()]
    hoje = datetime.now().date()
    
    # Direções para o sistema aprender: S, SW e SE são piores que N, E, W
    direcoes_possiveis = ['N', 'S', 'E', 'W', 'NE', 'NW', 'SE', 'SW', 'SSW', 'SSE']

    for d in range(365, -30, -1): # Gerando 365 dias atrás até 30 dias à frente
        data_alvo = hoje - timedelta(days=d)
        data_str = data_alvo.strftime('%Y-%m-%d')
        mes = data_alvo.month
        
        # 1. Física do Mar Variável
        onda = round(random.uniform(0.4, 3.5), 2)
        periodo = round(random.uniform(5.0, 14.0), 1) # Período agora varia!
        rajada = round(random.uniform(5.0, 25.0), 1)
        direcao = random.choice(direcoes_possiveis)
        
        temp_base = 28 if mes in [12, 1, 2, 3] else 20 if mes in [6, 7, 8] else 24
        temp = round(random.uniform(temp_base - 3, temp_base + 4), 1)
        chuva = round(random.uniform(0, 100), 1)
        
        res_cal = get_calendar_tags(data_alvo)

        # Grava Contexto (15 colunas batendo com o novo Daily_Context)
        cursor.execute('INSERT INTO Daily_Context VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', 
                     (data_str, onda, periodo, rajada, direcao, temp, 'Variável', chuva, 
                      res_cal[0], res_cal[1], res_cal[2], res_cal[3], res_cal[4], 0, None))

        # 2. Vendas com Lógica Física (Para o modelo aprender a correlação)
        if d > 0:
            for meal_id in ids_reais:
                base_venda = random.randint(15, 30)
                m_real = 1.0
                
                # Multiplicadores de Calendário
                if res_cal[1]: m_real *= 2.3     # Feriado bombando
                elif res_cal[0]: m_real *= 1.6   # FDS
                
                # A "NOVA" FÍSICA NO HISTÓRICO:
                # Se o sistema ler isso no passado, ele entende o impacto futuro
                score_fisico = (onda ** 2) * periodo
                if any(x in direcao for x in ['S', 'SW', 'SE']):
                    score_fisico *= 1.5 # Vento Sul castiga mais
                
                # Se o score for alto (> 45), as vendas caem de verdade no histórico
                if score_fisico > 50: m_real *= 0.40
                elif score_fisico > 30: m_real *= 0.75
                
                if chuva > 60: m_real *= 0.70

                venda_real = max(1, int(base_venda * m_real + random.gauss(0, 2)))

                cursor.execute("INSERT INTO Orders (data, meal_id, quantidade_pedida) VALUES (?,?,?)", 
                             (data_str, meal_id, venda_real))

                # Snapshot para Auditoria
                venda_prevista = int(venda_real * random.uniform(0.85, 1.15))
                cursor.execute("INSERT INTO Daily_Snapshots VALUES (?,?,?,?)", 
                             (data_str, meal_id, venda_prevista, venda_real))
    
    conn.commit()
    conn.close()
    print("✅ Banco de dados resetado e histórico inteligente gerado!")

if __name__ == "__main__":
    seed_everything()