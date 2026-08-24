
import requests
import hashlib
from datetime import datetime

HOYMILES_USER = "renato93@gmail.com"
HOYMILES_PASS = "mcosta295@"

TELEGRAM_BOT_TOKEN = "8946039720:AAF7U0QokemhGv_5iTzVj9L6IGB1C1kOvhE"
TELEGRAM_CHAT_ID = "1020154663"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Content-Type": "application/json",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    "Origin": "https://global.hoymiles.com",
    "Referer": "https://global.hoymiles.com/website/login"
}

def get_md5(texto):
    return hashlib.md5(texto.encode('utf-8')).hexdigest()

def autenticar():
    # Gateways regionais oficiais da Hoymiles (Global, Europa, Américas e Ásia)
    servidores = [
        "https://global.hoymiles.com/pvm-api",
        "https://eu2.hoymiles.com/pvm-api",
        "https://us.hoymiles.com/pvm-api",
        "https://cn.hoymiles.com/pvm-api",
        "https://global.hoymiles.com/api/0"
    ]
    
    payloads = [
        {"user_name": HOYMILES_USER, "password": get_md5(HOYMILES_PASS), "language": "pt_BR"},
        {"user_name": HOYMILES_USER, "password": HOYMILES_PASS, "language": "pt_BR"},
        {"account": HOYMILES_USER, "password": get_md5(HOYMILES_PASS)},
        {"account": HOYMILES_USER, "password": HOYMILES_PASS}
    ]
    
    for base in servidores:
        url = f"{base}/login"
        for p in payloads:
            try:
                res = requests.post(url, json=p, headers=HEADERS, timeout=12)
                print(f"Tentando {url} -> HTTP {res.status_code}")
                if res.status_code == 200:
                    data_json = res.json()
                    print(f"Retorno: {data_json}")
                    
                    if str(data_json.get("status")) == "0" or str(data_json.get("code")) == "0":
                        dados = data_json.get("data", {})
                        token = dados.get("token") or dados.get("token_id") or dados.get("access_token")
                        if token:
                            print(f"--> LOGIN EFETUADO COM SUCESSO NO GATEWAY: {base}")
                            return token, base
            except Exception as e:
                print(f"Erro em {url}: {e}")
                
    return None, None

def obter_dados_usina(token, base_api):
    url = f"{base_api}/station/select_station"
    headers = HEADERS.copy()
    headers["Authorization"] = token
    headers["token"] = token
    payload = {"page": 1, "page_size": 10}
    
    try:
        res = requests.post(url, json=payload, headers=headers, timeout=15)
        res_json = res.json()
        stations = res_json.get("data", {}).get("list", [])
        return stations[0] if stations else None
    except Exception as e:
        print(f"Erro usina: {e}")
        return None

def obter_microinversores(token, base_api, station_id):
    url = f"{base_api}/dev/select_mi"
    headers = HEADERS.copy()
    headers["Authorization"] = token
    headers["token"] = token
    payload = {"sid": station_id, "page": 1, "page_size": 50}
    
    try:
        res = requests.post(url, json=payload, headers=headers, timeout=15)
        res_json = res.json()
        return res_json.get("data", {}).get("list", [])
    except Exception as e:
        print(f"Erro microinversores: {e}")
        return []

def enviar_telegram(mensagem):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": mensagem,
        "parse_mode": "Markdown"
    }
    try:
        res = requests.post(url, json=payload, timeout=10)
        print(f"Telegram status: {res.status_code}")
    except Exception as e:
        print(f"Erro Telegram: {e}")

def main():
    token, base_api = autenticar()
    if not token:
        print("Login não realizado.")
        return

    usina = obter_dados_usina(token, base_api)
    if not usina:
        print("Nenhuma usina encontrada.")
        return

    sid = usina.get("sid") or usina.get("id")
    inversores = obter_microinversores(token, base_api, sid)

    agora = datetime.now().strftime("%d/%m/%Y - %H:%M")
    status_usina = "🟢 Online (Gerando)" if usina.get("status") == 1 else "🔴 Offline / Repouso"
    
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
    print("Processo concluído e mensagem enviada com sucesso!")

if __name__ == "__main__":
    main()

