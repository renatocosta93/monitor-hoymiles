
import requests
from hoymiles_s_miles_cloud import HoymilesClient
from datetime import datetime

# ==========================================
# CONFIGURAÇÕES DA CONTA HOYMILES E TELEGRAM
# ==========================================
HOYMILES_USER = "renato93@gmail.com"
HOYMILES_PASS = "mcosta295@"

# Seus dados do Telegram configurados anteriormente:
TELEGRAM_BOT_TOKEN = "8946039720:AAF7U0QokemhGv_5iTzVj9L6IGB1C1kOvhE"
TELEGRAM_CHAT_ID = "1020154663"

def enviar_telegram(mensagem):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": mensagem,
        "parse_mode": "Markdown"
    }
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Erro ao enviar para o Telegram: {e}")

def main():
    try:
        client = HoymilesClient(
            username=HOYMILES_USER,
            password=HOYMILES_PASS
        )
        client.login()
        
        # 1. Coleta dados da Usina
        plantas = client.get_plant_list()
        if not plantas:
            print("Nenhuma usina encontrada.")
            return

        usina = plantas[0]
        sid = usina.get("id") or usina.get("sid")
        
        # 2. Coleta dados em tempo real da usina
        real_data = client.get_real_data(sid) if sid else {}
        
        # 3. Coleta dados dos microinversores
        microinversores = client.get_microinverters(sid) if sid else []

        agora = datetime.now().strftime("%d/%m/%Y - %H:%M")
        
        # Formatação do Painel
        msg = f"☀️ *PAINEL SOLAR HOYMILES* ☀️\n"
        msg += f"📅 `{agora}`\n\n"
        
        msg += f"📊 *GERAÇÃO DA USINA*\n"
        msg += f"• *Potência Atual:* `{real_data.get('real_power', usina.get('real_power', 0))} W`\n"
        msg += f"• *Hoje:* `{real_data.get('today_eq', usina.get('today_eq', 0))} kWh`\n"
        msg += f"• *Mês:* `{real_data.get('month_eq', usina.get('month_eq', 0))} kWh`\n"
        msg += f"• *Total Acumulado:* `{real_data.get('total_eq', usina.get('total_eq', 0))} kWh`\n\n"
        
        if microinversores:
            msg += f"🔌 *MICROINVERSORES & REDE*\n"
            for idx, inv in enumerate(microinversores, start=1):
                sn = inv.get("sn", f"Inv {idx}")
                temp = inv.get("temperature", "--")
                pot = inv.get("real_power", 0)
                tensao = inv.get("grid_voltage", "--")
                msg += f"• *Inv {idx} ({sn})*: {pot} W | {temp}°C | {tensao} V\n"

        enviar_telegram(msg)
        print("Relatório enviado para o Telegram com sucesso!")

    except Exception as e:
        print(f"Erro na execução: {e}")

if __name__ == "__main__":
    main()
