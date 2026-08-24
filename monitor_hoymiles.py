
import json
import re
import requests
from datetime import datetime
from playwright.sync_api import sync_playwright

# ==========================================
# CREDENCIAIS CONFIGURADAS
# ==========================================
HOYMILES_USER = "renato93@gmail.com"
HOYMILES_PASS = "mcosta295@"

TELEGRAM_BOT_TOKEN = "8946039720:AAF7U0QokemhGv_5iTzVj9L6IGB1C1kOvhE"
TELEGRAM_CHAT_ID = "1020154663"

captured_responses = []

def interceptar_resposta(response):
    try:
        if "application/json" in response.headers.get("content-type", ""):
            data = response.json()
            if isinstance(data, dict) and "data" in data:
                captured_responses.append({"url": response.url, "body": data})
    except Exception:
        pass

def enviar_telegram(mensagem):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": mensagem,
        "parse_mode": "Markdown"
    }
    try:
        res = requests.post(url, json=payload, timeout=15)
        print(f"Status Envio Telegram: {res.status_code}")
    except Exception as e:
        print(f"Erro ao enviar Telegram: {e}")

def main():
    print("Iniciando navegador automatizado...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800}
        )
        page = context.new_page()
        page.on("response", interceptar_resposta)

        try:
            print("Acessando tela de login Hoymiles...")
            page.goto("https://global.hoymiles.com/website/login", timeout=60000)
            page.wait_for_timeout(4000)

            # Preenche o campo de usuário
            user_input = page.locator("input[type='text'], input[placeholder*='usuário' i], input[placeholder*='user' i], input[placeholder*='account' i]").first
            user_input.fill(HOYMILES_USER)

            # Preenche o campo de senha
            pass_input = page.locator("input[type='password']").first
            pass_input.fill(HOYMILES_PASS)

            # Clica em checkbox de aceite/termos caso exista
            checkbox = page.locator(".el-checkbox__input, input[type='checkbox']").first
            if checkbox.is_visible():
                checkbox.click()

            # Clica no botão de Login
            login_button = page.locator("button[type='submit'], button.el-button--primary, button:has-text('Entrar'), button:has-text('Log In'), button:has-text('Login')").first
            login_button.click()
            print("Login submetido, aguardando carregamento do painel...")

            page.wait_for_timeout(10000)
            print(f"Página atual: {page.url}")

        except Exception as e:
            print(f"Erro durante a navegação: {e}")
        finally:
            browser.close()

    # Processa os dados interceptados
    real_power = 0
    today_eq = 0
    month_eq = 0
    total_eq = 0
    inversores_info = []

    for item in captured_responses:
        body = item["body"]
        data = body.get("data", {})
        
        # Se for objeto de lista de usinas ou resumo
        if isinstance(data, dict):
            if "real_power" in data or "today_eq" in data:
                real_power = data.get("real_power", real_power)
                today_eq = data.get("today_eq", today_eq)
                month_eq = data.get("month_eq", month_eq)
                total_eq = data.get("total_eq", total_eq)
            
            # Se contiver lista interna
            if "list" in data and isinstance(data["list"], list):
                for row in data["list"]:
                    if isinstance(row, dict):
                        if "real_power" in row or "today_eq" in row:
                            real_power = row.get("real_power", real_power)
                            today_eq = row.get("today_eq", today_eq)
                            month_eq = row.get("month_eq", month_eq)
                            total_eq = row.get("total_eq", total_eq)
                        if "sn" in row or "model" in row:
                            inversores_info.append(row)

    agora = datetime.now().strftime("%d/%m/%Y - %H:%M")
    status_str = "🟢 Online (Gerando)" if float(real_power or 0) > 0 else "🌙 Offline / Repouso"

    msg = f"☀️ *PAINEL SOLAR HOYMILES* ☀️\n"
    msg += f"📅 `{agora}`\n\n"
    msg += f"📊 *GERAÇÃO DA USINA*\n"
    msg += f"• *Potência Atual:* `{real_power} W`\n"
    msg += f"• *Hoje:* `{today_eq} kWh`\n"
    msg += f"• *Mês:* `{month_eq} kWh`\n"
    msg += f"• *Total Acumulado:* `{total_eq} kWh`\n"
    msg += f"• *Status:* {status_str}\n\n"

    if inversores_info:
        msg += f"🔌 *MICROINVERSORES*\n"
        for idx, inv in enumerate(inversores_info, start=1):
            sn = inv.get("sn", f"Inv {idx}")
            temp = inv.get("temperature", "--")
            pot = inv.get("real_power", 0)
            msg += f"• *{sn}*: {pot} W | {temp}°C\n"

    enviar_telegram(msg)
    print("Execução finalizada com sucesso!")

if __name__ == "__main__":
    main()

