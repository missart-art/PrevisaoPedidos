import sqlite3

def popular_banco():
    conn = sqlite3.connect("sistema_previsao.db")
    cursor = conn.cursor()

    # 1. Cadastrar Pratos
    cursor.execute("DELETE FROM Meals WHERE nome_prato = 'Banana'")
    
    conn.commit()
    conn.close()
    print("deu!")

if __name__ == "__main__":
    popular_banco()