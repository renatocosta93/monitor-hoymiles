
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

captured_data = []

def interceptar_resposta(response):
    try:
        if "application/json" in response.headers.get("content-type", ""):
            data = response.json()
            if isinstance(data, dict):
                captured_data.append({"url": response.url, "data": data})
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
        print(f"Status Telegram: {res.status_code}")
    except Exception as e:
        print(f"Erro Telegram: {e}")

def extrair_valor(dicionario, chaves):
    for k in chaves:
        if k in dicionario and dicionario[k] is not None:
            return dicionario[k]
    return None

def main():
    print("Iniciando navegador Playwright...")
    dom_text = ""

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            viewport={"width": 1440, "height": 900}
        )
        page = context.new_page()
        page.on("response", interceptar_resposta)

        try:
            print("Acessando tela de login...")
            page.goto("https://global.hoymiles.com/website/login", wait_until="networkidle", timeout=60000)
            page.wait_for_timeout(3000)

            # Preenchimento dos campos de acesso
            user_input = page.locator("input[type='text'], input[placeholder*='usuário' i], input[placeholder*='user' i], input[placeholder*='account' i]").first
            user_input.fill(HOYMILES_USER)

            pass_input = page.locator("input[type='password']").first
            pass_input.fill(HOYMILES_PASS)

            # Checkbox de termos (caso visível)
            checkbox = page.locator(".el-checkbox__input, input[type='checkbox']").first
            if checkbox.is_visible():
                checkbox.click()

            # Botão de Login
            login_btn = page.locator("button[type='submit'], button.el-button--primary, button:has-text('Entrar'), button:has-text('Log In'), button:has-text('Login')").first
            login_btn.click()
            print("Login submetido...")

            # Aguarda a saída da tela de login e o carregamento do painel
            page.wait_for_timeout(15000)
            page.wait_for_load_state("networkidle")
            print(f"URL após login: {page.url}")

            # Se houver lista de usinas, tenta clicar na primeira usina
            usina_link = page.locator(".station-name, .plant-name, .table-row, a[href*='overview']").first
            if usina_link.is_visible():
                usina_link.click()
                page.wait_for_timeout(6000)

            dom_text = page.inner_text("body")

        except Exception as e:
            print(f"Erro na navegação: {e}")
        finally:
            browser.close()

    # Processamento e extração dos dados
    real_power = None
    today_eq = None
    month_eq = None
    total_eq = None
    inversores_info = []

    # 1. Varredura dos JSONs interceptados (suporta snake_case e camelCase)
    chaves_potencia = ["real_power", "realPower", "pac", "power", "real_p"]
    chaves_hoje = ["today_eq", "todayEq", "today_energy", "todayEnergy", "e_today"]
    chaves_mes = ["month_eq", "monthEq", "month_energy", "monthEnergy", "e_month"]
    chaves_total = ["total_eq", "totalEq", "total_energy", "totalEnergy", "e_total"]

    for item in captured_data:
        body = item.get("data", {})
        
        def varrer_objeto(obj):
            nonlocal real_power, today_eq, month_eq, total_eq
            if isinstance(obj, dict):
                p = extrair_valor(obj, chaves_potencia)
                if p is not None and real_power is None: real_power = p
                
                h = extrair_valor(obj, chaves_hoje)
                if h is not None and today_eq is None: today_eq = h

                m = extrair_valor(obj, chaves_mes)
                if m is not None and month_eq is None: month_eq = m

                t = extrair_valor(obj, chaves_total)
                if t is not None and total_eq is None: total_eq = t

                if "sn" in obj or "mi_sn" in obj or "model" in obj:
                    inversores_info.append(obj)

                for v in obj.values():
                    varrer_objeto(v)
            elif isinstance(obj, list):
                for elem in obj:
                    varrer_objeto(elem)

        varrer_objeto(body)

    # 2. Fallback de extração via texto do DOM caso JSON venha aninhado
    if real_power is None:
        p_match = re.search(r'(\d+[\.,]?\d*)\s*(?:W|kW)\b', dom_text)
        real_power = p_match.group(0) if p_match else "0 W"
    else:
        real_power = f"{real_power} W"

    today_eq = f"{today_eq} kWh" if today_eq is not None else "-- kWh"
    month_eq = f"{month_eq} kWh" if month_eq is not None else "-- kWh"
    total_eq = f"{total_eq} kWh" if total_eq is not None else "-- kWh"

    agora = datetime.now().strftime("%d/%m/%Y - %H:%M")
    
    # Formatação do Painel Solar
    msg = f"☀️ *PAINEL SOLAR HOYMILES* ☀️\n"
    msg += f"📅 `{agora}`\n\n"
    msg += f"📊 *GERAÇÃO DA USINA*\n"
    msg += f"• *Potência Atual:* `{real_power}`\n"
    msg += f"• *Hoje:* `{today_eq}`\n"
    msg += f"• *Mês:* `{month_eq}`\n"
    msg += f"• *Total Acumulado:* `{total_eq}`\n\n"

    if inversores_info:
        msg += f"🔌 *MICROINVERSORES*\n"
        vistos = set()
        for idx, inv in enumerate(inversores_info, start=1):
            sn = inv.get("sn") or inv.get("mi_sn") or f"Inv {idx}"
            if sn in vistos: continue
            vistos.add(sn)
            temp = inv.get("temperature") or inv.get("temp") or "--"
            pot = inv.get("real_power") or inv.get("realPower") or inv.get("power") or "--"
            msg += f"• *{sn}*: `{pot} W` | `{temp}°C`\n"

    enviar_telegram(msg)
    print("Execução finalizada e enviada para o Telegram!")

if __name__ == "__main__":
    main()
