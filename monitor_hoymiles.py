import requests
import json
from datetime import datetime

# ==========================================
# CONFIGURAÇÕES DA CONTA HOYMILES E TELEGRAM
# ==========================================
HOYMILES_USER = "renato93@gmail.com"
HOYMILES_PASS = "mcosta295@"

# Obtenha esses dois dados no Telegram (instruções no passo a passo abaixo):
TELEGRAM_BOT_TOKEN = "SEU_TOKEN_DO_BOT"
TELEGRAM_CHAT_ID = "SEU_CHAT_ID"

BASE_URL = "https://global.hoymiles.com/pvm/api/0"

def autenticar():
    url = f"{BASE_URL}/login"
    payload = {
        "user_name": HOYMILES_USER,
        "password": HOYMILES_PASS
    }
    headers = {"Content-Type": "application/json"}
    
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=15)
        res_json = response.json()
        if res_json.get("status") == "0" and "data" in res_json:
            return res_json["data"].get("token") or res_json["data"].get("token_id")
        print(f"Erro no login: {res_json.get('message')}")
        return None
    except Exception as e:
        print(f"Exceção na autenticação: {e}")
        return None

def obter_dados_usina(token):
    url = f"{BASE_URL}/station/select_station"
    headers = {"Authorization": token, "Content-Type": "application/json"}
    payload = {"page": 1, "page_size": 10}
    
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=15)
        res_json = response.json()
        stations = res_json.get("data", {}).get("list", [])
        return stations[0] if stations else None
    except Exception as e:
        print(f"Erro ao obter usina: {e}")
        return None

def obter_microinversores(token, station_id):
    url = f"{BASE_URL}/dev/select_mi"
    headers = {"Authorization": token, "Content-Type": "application/json"}
    payload = {"sid": station_id, "page": 1, "page_size": 50}
    
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=15)
        res_json = response.json()
        return res_json.get("data", {}).get("list", [])
    except Exception as e:
        print(f"Erro ao obter microinversores: {e}")
        return []

def enviar_telegram(mensagem):
    url = f"https://api.telegram.org/bot{8946039720:AAF7U0QokemhGv_5iTzVj9L6IGB1C1kOvhE}/sendMessage"
    payload = {
        "chat_id":1020154663,
        "text": mensagem,
        "parse_mode": "Markdown"
    }
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Erro ao enviar para o Telegram: {e}")

def main():
    token = autenticar()
    if not token:
        print("Não foi possível autenticar.")
        return

    usina = obter_dados_usina(token)
    if not usina:
        print("Nenhuma usina localizada.")
        return

    sid = usina.get("sid")
    inversores = obter_microinversores(token, sid)

    agora = datetime.now().strftime("%d/%m/%Y - %H:%M")
    status_usina = "🟢 Online (Gerando)" if usina.get("status") == 1 else "🔴 Offline / Repouso"
    
    # Montagem do Painel
    msg = f"☀️ *PAINEL SOLAR HOYMILES* ☀️\n"
    msg += f"📅 `{agora}`\n\n"
    
    msg += f"📊 *GERAÇÃO DA USINA*\n"
    msg += f"• *Potência Atual:* `{usina.get('real_power', 0)} W`\n"
    msg += f"• *Hoje:* `{usina.get('today_eq', 0)} kWh`\n"
    msg += f"• *Mês:* `{usina.get('month_eq', 0)} kWh`\n"
    msg += f"• *Total Acumulado:* `{usina.get('total_eq', 0)} kWh`\n"
    msg += f"• *Status:* {status_usina}\n\n"
    
    if inversores:
        msg += f"🔌 *MICROINVERSORES & REDE*\n"
        for idx, inv in enumerate(inversores, start=1):
            sn = inv.get("sn", f"Inv {idx}")
            temp = inv.get("temperature", "--")
            pot = inv.get("real_power", 0)
            tensao = inv.get("grid_voltage", "--")
            msg += f"• *Inv {idx} ({sn})*: {pot} W | {temp}°C | {tensao} V\n"
    
    co2 = usina.get("co2_emission_reduction", 0)
    msg += f"\n🌱 *Impacto:* `{co2} kg` CO₂ evitados"

    enviar_telegram(msg)
    print("Relatório enviado com sucesso!")

if __name__ == "__main__":
    main()
