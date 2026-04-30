import requests
import cloudscraper 
from bs4 import BeautifulSoup
import holidays
from datetime import datetime, timedelta
import streamlit as st
import json
import re

scraper = cloudscraper.create_scraper() # Cria o "espião"

CITY = "Ilhabela"
WINDGURU_ID = "184698"

def fetch_google_weather(city):
    """Busca o clima no Google com tratamento de erro robusto."""
    url = f"https://www.google.com/search?q=previsao+do+tempo+{city.replace(' ', '+')}&hl=pt-BR"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    try:
        response = scraper.get(url, headers=headers, timeout=10)
        response.encoding = 'utf-8'
        soup = BeautifulSoup(response.text, "html.parser")

        # Tentamos capturar os elementos. Se o Google mudar o ID, o .get() evita o crash
        temp_el = soup.find("span", id="wob_tm")
        cond_el = soup.find("span", id="wob_dc")
        rain_el = soup.find("span", id="wob_pp")

        if temp_el and cond_el and rain_el:
            return {
                "temp_max": float(temp_el.text),
                "condicao": cond_el.text.capitalize(),
                "chuva_prob": float(rain_el.text.replace('%', ''))
            }
        else:
            raise ValueError("Google mudou o layout dos IDs")

    except Exception as e:
        # Se falhar o Google, ele vai para o Fallback automaticamente
        return fetch_fallback_weather(city)

def fetch_fallback_weather(city):
    url = f"https://wttr.in/{city}?format=j1&lang=pt"
    try:
        data = requests.get(url, timeout=10).json()
        grade_clima = {}
        for idx, dia in enumerate(data['weather']):
            hourly = dia['hourly'][0] # Pega dados do meio-dia
            grade_clima[idx] = {
                "temp_max": float(dia['maxtempC']),
                "condicao": hourly['weatherDesc'][0]['value'].capitalize(),
                "chuva_prob": float(hourly['chanceofrain'])
            }
        return grade_clima
    except:
        grade_clima = 'Sem dados'
        return grade_clima

def fetch_windguru_data(spot_id="184698"):
    url = f"https://www.windguru.cz/{spot_id}"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36", 
                "Referer": "https://www.windguru.cz/184698"
        }
    try:
        response = scraper.get(url, headers=headers, timeout=15)
        # Captura o JSON bruto dentro do HTML
        print(f"A variável existe no HTML? {'wg_forecast_json' in response.text}")
        pattern = re.compile(r"wg_forecast_json\s*=\s*(\{.*?\});", re.DOTALL)
        match = pattern.search(response.text)
        #print(match)
        if match:
            data = json.loads(match.group(1))
            model_id = list(data['fcst'].keys())[0]
            fcst = data['fcst'][model_id]
            
            # Mapeia os dados pulando de 24h em 24h (8 índices de 3h)
            grade = {}
            for i in range(0, len(fcst['htsgw']), 8):
                dia_idx = i // 8
                grade[dia_idx] = {
                    "onda_altura": float(fcst['htsgw'][i]),
                    "onda_periodo": float(fcst['perpw'][i]),
                    "vento_rajada": float(fcst['gust'][i]),
                    "vento_direcao": str(fcst['dir'][i])
                }
                
            return grade
    except Exception as e:
        print(f"Erro Windguru: {e}")
    return None

def sync_external_data(conn):
    cursor = conn.cursor()
    hoje = datetime.now().date()
    
    # Coleta as grades completas de uma vez
    grade_mar = fetch_windguru_data(WINDGURU_ID)
    grade_clima = fetch_fallback_weather(CITY)

    with st.spinner("Sincronizando grade de previsão..."):
        for i in range(30):
            data_alvo = hoje + timedelta(days=i)
            data_str = data_alvo.strftime('%Y-%m-%d')
            cal = get_calendar_tags(data_alvo)

            # Busca o dia específico dentro da grade coletada
            mar = grade_mar.get(i) if grade_mar else None
            clima = grade_clima.get(i) if grade_clima else None

            cursor.execute('''
                INSERT OR REPLACE INTO Daily_Context 
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ''', (
                data_str, 
                mar['onda_altura'] if mar else None, mar['onda_periodo'] if mar else None, 
                mar['vento_rajada'] if mar else None, mar['vento_direcao'] if mar else None,
                clima['temp_max'] if clima else None, clima['condicao'] if clima else None, clima['chuva_prob'] if clima else None,
                cal[0], cal[1], cal[2], cal[3], cal[4], 0, None
            ))
    conn.commit()

def get_nth_business_day(year, month, n):
    """Calcula o N-ésimo dia útil do mês."""
    br_holidays = holidays.BR()
    count = 0
    for day in range(1, 32):
        try:
            date_obj = datetime(year, month, day).date()
            # Se não é fim de semana nem feriado, conta como dia útil
            if date_obj.weekday() < 5 and date_obj not in br_holidays:
                count += 1
            if count == n:
                return day
        except ValueError:
            break
    return 31

def get_calendar_tags(data):
    """Identifica fds, feriados, pontes e período do mês (Início/Fim)."""
    br_holidays = holidays.BR()
    is_weekend = 1 if data.weekday() >= 5 else 0
    is_holiday = 1 if data in br_holidays else 0
    
    # Lógica de Início/Fim de Mês baseada em Dias Úteis
    quinto_dia_util = get_nth_business_day(data.year, data.month, 5)
    quarto_dia_util = get_nth_business_day(data.year, data.month, 4)
    
    is_start_of_month = 1 if (data.day >= quinto_dia_util and data.day <= 20) else 0
    is_end_of_month = 1 if (data.day >= 21 or data.day <= quarto_dia_util) else 0

    is_bridge = 0
    if not is_holiday and not is_weekend:
        terca = data + timedelta(days=1) if data.weekday() == 0 else None
        quinta = data - timedelta(days=1) if data.weekday() == 4 else None
        if (terca and terca in br_holidays) or (quinta and quinta in br_holidays):
            is_bridge = 1
            
    return is_weekend, is_holiday, is_bridge, is_start_of_month, is_end_of_month


if __name__ == "__main__":
    from database import setup_database
    conn = setup_database()
    sync_external_data(conn)
    print(f"Dados sincronizados para {CITY} via Google e Windguru.")
    print(fetch_windguru_data("184698")) # Tem que imprimir um dicionário com números, não 'None'