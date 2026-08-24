import json
import re
import requests
from datetime import datetime, timezone, timedelta
from playwright.sync_api import sync_playwright

# ==========================================
# CONFIGURAÇÕES E CREDENCIAIS
# ==========================================
HOYMILES_USER = "renato93@gmail.com"
HOYMILES_PASS = "mcosta295@"

TELEGRAM_BOT_TOKEN = "8946039720:AAF7U0QokemhGv_5iTzVj9L6IGB1C1kOvhE"
TELEGRAM_CHAT_ID = "1020154663"

POTENCIA_INSTALADA_WP = 2000.0  # Potência total da usina (Wp)
TARIFA_KWH = 0.88               # Tarifa de energia (R$/kWh)

# Fuso Horário de Brasília (UTC-3)
FUSO_BR = timezone(timedelta(hours=-3))

captured_data = []

def interceptar_resposta(response):
    try:
        if "application/json" in response.headers.get("content-type", ""):
            data = response.json()
            if isinstance(data, dict):
                captured_data.append({"url": response.url, "data": data})
    except Exception:
        pass

def converter_energia(valor):
    if valor is None:
        return 0.0
    try:
        num = float(str(valor).replace(",", "."))
        if num > 500:
            return round(num / 1000.0, 2)
        return round(num, 2)
    except Exception:
        return 0.0

def converter_co2(valor):
    if valor is None:
        return 0.0
    try:
        num = float(str(valor).replace(",", "."))
        if num > 500:
            return round(num / 1000.0, 2)
        return round(num, 2)
    except Exception:
        return 0.0

def extrair_campo(obj, chaves):
    if isinstance(obj, dict):
        for k in chaves:
            if k in obj and obj[k] not in [None, "", "--"]:
                return obj[k]
    return None

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
        print(f"Erro ao enviar Telegram: {e}")

def main():
    print("Iniciando coleta Playwright com navegação estendida...")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            viewport={"width": 1440, "height": 900}
        )
        page = context.new_page()
        page.on("response", interceptar_resposta)

        try:
            # 1. Login
            page.goto("https://global.hoymiles.com/website/login", wait_until="networkidle", timeout=60000)
            page.wait_for_timeout(3000)

            page.locator("input[type='text'], input[placeholder*='usuário' i], input[placeholder*='user' i], input[placeholder*='account' i]").first.fill(HOYMILES_USER)
            page.locator("input[type='password']").first.fill(HOYMILES_PASS)

            checkbox = page.locator(".el-checkbox__input, input[type='checkbox']").first
            if checkbox.is_visible():
                checkbox.click()

            page.locator("button[type='submit'], button.el-button--primary, button:has-text('Entrar'), button:has-text('Login')").first.click()

            page.wait_for_timeout(10000)
            page.wait_for_load_state("networkidle")

            # 2. Acessar usina
            usina_btn = page.locator(".station-name, .plant-name, .table-row, a[href*='overview']").first
            if usina_btn.is_visible():
                usina_btn.click()
                page.wait_for_timeout(5000)

            # 3. Navegar nas abas internas de componentes e dispositivos
            tabs_para_clicar = [
                "//div[contains(@class, 'el-tabs__item') and (contains(., 'Dispositivo') or contains(., 'Device') or contains(., 'Equipamento'))]",
                "//div[contains(@class, 'el-tabs__item') and (contains(., 'Layout') or contains(., 'Componente'))]",
                "//li[contains(@class, 'el-menu-item') and (contains(., 'Dispositivo') or contains(., 'Device'))]"
            ]

            for selector in tabs_para_clicar:
                elem = page.locator(selector).first
                if elem.is_visible():
                    elem.click()
                    page.wait_for_timeout(5000)
                    page.wait_for_load_state("networkidle")

        except Exception as e:
            print(f"Aviso na navegação: {e}")
        finally:
            browser.close()

    # Variáveis consolidadas
    real_power_val = 0.0
    today_eq_raw = None
    month_eq_raw = None
    total_eq_raw = None
    peak_power = 0.0
    co2_raw = None
    start_time_raw = None
    grid_v = "--"
    grid_f = "--"
    grid_i = "--"
    power_factor = "--"
    alarmes_detectados = []
    inversores_dict = {}

    def varrer_json(obj):
        nonlocal real_power_val, today_eq_raw, month_eq_raw, total_eq_raw
        nonlocal peak_power, co2_raw, start_time_raw, grid_v, grid_f, grid_i, power_factor
        
        if isinstance(obj, dict):
            # Potência e Energia
            p = extrair_campo(obj, ["real_power", "realPower", "pac", "power", "real_p"])
            if p is not None and real_power_val == 0.0:
                try: real_power_val = float(str(p).replace(",", "."))
                except: pass

            h = extrair_campo(obj, ["today_eq", "todayEq", "today_energy", "e_today"])
            if h is not None and today_eq_raw is None: today_eq_raw = h

            m = extrair_campo(obj, ["month_eq", "monthEq", "month_energy", "e_month"])
            if m is not None and month_eq_raw is None: month_eq_raw = m

            t = extrair_campo(obj, ["total_eq", "totalEq", "total_energy", "e_total"])
            if t is not None and total_eq_raw is None: total_eq_raw = t

            pk = extrair_campo(obj, ["peak_power", "peakPower", "max_power"])
            if pk is not None and peak_power == 0.0:
                try: peak_power = float(str(pk).replace(",", "."))
                except: pass

            co2 = extrair_campo(obj, ["co2_emission_reduction", "co2_eq", "co2_reduction"])
            if co2 is not None and co2_raw is None: co2_raw = co2

            # Início de geração / Horário de ativação
            st = extrair_campo(obj, ["start_time", "start_gen_time", "online_time", "create_time", "connect_time", "grid_connection_date"])
            if st is not None and start_time_raw is None:
                start_time_raw = str(st)

            # Rede Elétrica CA
            gv = extrair_campo(obj, ["grid_voltage", "gridVoltage", "v_ac", "vac", "voltage", "vol"])
            if gv is not None and grid_v == "--": grid_v = str(gv)

            gf = extrair_campo(obj, ["grid_frequency", "gridFrequency", "frequency", "fac", "freq"])
            if gf is not None and grid_f == "--": grid_f = str(gf)

            gi = extrair_campo(obj, ["grid_current", "gridCurrent", "i_ac", "iac", "current"])
            if gi is not None and grid_i == "--": grid_i = str(gi)

            pf = extrair_campo(obj, ["power_factor", "powerFactor", "cos_phi", "pf"])
            if pf is not None and power_factor == "--": power_factor = str(pf)

            # Alarmes
            al = extrair_campo(obj, ["warn_list", "alarm_list", "alarm_code", "alarms"])
            if al and isinstance(al, list):
                for item_al in al:
                    if item_al and str(item_al) not in alarmes_detectados:
                        alarmes_detectados.append(str(item_al))

            # Microinversores
            sn = extrair_campo(obj, ["sn", "mi_sn", "inverter_sn", "device_sn"])
            if sn and str(sn).isdigit() and len(str(sn)) >= 10:
                sn_str = str(sn)
                if sn_str not in inversores_dict:
                    inversores_dict[sn_str] = obj
                else:
                    inversores_dict[sn_str].update(obj)

            for v in obj.values():
                varrer_json(v)
        elif isinstance(obj, list):
            for item in obj:
                varrer_json(item)

    for item in captured_data:
        varrer_json(item.get("data", {}))

    # Conversões e Cálculos
    today_kwh = converter_energia(today_eq_raw)
    month_kwh = converter_energia(month_eq_raw)
    total_kwh = converter_energia(total_eq_raw)

    eficiencia = round((real_power_val / POTENCIA_INSTALADA_WP) * 100, 1) if POTENCIA_INSTALADA_WP > 0 else 0
    hsp = round(today_kwh / (POTENCIA_INSTALADA_WP / 1000.0), 2) if POTENCIA_INSTALADA_WP > 0 else 0

    economia_dia = round(today_kwh * TARIFA_KWH, 2)
    economia_mes = round(month_kwh * TARIFA_KWH, 2)
    economia_total = round(total_kwh * TARIFA_KWH, 2)

    co2_evitado = converter_co2(co2_raw)
    arvores_equiv = round(co2_evitado / 20.0, 2)

    # Formatação de Início de Geração
    inicio_str = ""
    if start_time_raw:
        if " " in start_time_raw:
            inicio_str = f" | 🌅 Início: {start_time_raw.split(' ')[-1][:5]}"
        else:
            inicio_str = f" | 🌅 Início: {start_time_raw[:5]}"

    # Data e hora no Fuso Horário de Brasília
    agora_br = datetime.now(FUSO_BR).strftime("%d/%m/%Y - %H:%M")
    status_icon = "🟢 Online (Gerando)" if real_power_val > 10 else "🌙 Offline / Repouso"

    # Montagem da Mensagem
    msg = f"☀️ *PAINEL SOLAR HOYMILES* ☀️\n"
    msg += f"📅 `{agora_br}` | {status_icon}\n\n"

    msg += f"📊 *GERAÇÃO & RENDIMENTO*\n"
    msg += f"• *Potência Atual:* `{real_power_val:.1f} W` ({eficiencia}% da usina)\n"
    msg += f"• *Hoje:* `{today_kwh:.2f} kWh`"
    if peak_power > 0: msg += f" | *Pico:* `{peak_power:.0f} W`\n"
    else: msg += "\n"
    msg += f"• *Rendimento Diário (HSP):* `{hsp:.2f} h`{inicio_str}\n"
    msg += f"• *Mês Atual:* `{month_kwh:.2f} kWh`\n"
    msg += f"• *Total Histórico:* `{total_kwh:.2f} kWh`\n\n"

    msg += f"💰 *ECONOMIA ESTIMADA*\n"
    msg += f"• *Hoje:* `R$ {economia_dia:.2f}`\n"
    msg += f"• *Mês Atual:* `R$ {economia_mes:.2f}`\n"
    msg += f"• *Total Acumulado:* `R$ {economia_total:.2f}`\n\n"

    if grid_v != "--" or grid_f != "--":
        msg += f"⚡ *REDE ELÉTRICA (CA)*\n"
        msg += f"• *Tensão:* `{grid_v} V`"
        if grid_f != "--": msg += f" | *Frequência:* `{grid_f} Hz`"
        if grid_i != "--": msg += f" | *Corrente:* `{grid_i} A`"
        msg += "\n\n"

    if inversores_dict:
        msg += f"🔌 *MICROINVERSORES & PLACAS*\n"
        for sn, inv in inversores_dict.items():
            temp = inv.get("temperature") or inv.get("temp") or "--"
            pot = inv.get("real_power") or inv.get("realPower") or inv.get("power") or "--"
            v_inv = inv.get("grid_voltage") or inv.get("gridVoltage") or "--"

            detalhes = []
            if pot != "--": detalhes.append(f"{pot} W")
            if temp != "--": detalhes.append(f"{temp}°C")
            if v_inv != "--": detalhes.append(f"{v_inv} V")

            msg += f"• *{sn}* — `{' | '.join(detalhes)}`\n"

            ports = inv.get("port_list") or inv.get("channels") or inv.get("pv_list")
            if ports and isinstance(ports, list):
                for p_idx, port in enumerate(ports, start=1):
                    p_w = port.get("power") or port.get("real_power") or "--"
                    p_v = port.get("voltage") or port.get("v_dc") or "--"
                    p_i = port.get("current") or port.get("i_dc") or "--"
                    msg += f"  └ PV{p_idx}: `{p_v} V` | `{p_i} A` | `{p_w} W`\n"
        msg += "\n"

    msg += f"📡 *HARDWARE & DIAGNÓSTICO*\n"
    if alarmes_detectados:
        msg += f"• *Alarmes:* ⚠️ `{' | '.join(alarmes_detectados)}`\n\n"
    else:
        msg += f"• *Alarmes:* 🟢 Nenhum alarme ativo\n\n"

    msg += f"🌱 *IMPACTO AMBIENTAL*\n"
    msg += f"• *CO₂ Total Evitado:* `{co2_evitado:.2f} kg` (~{arvores_equiv} árvores)"

    enviar_telegram(msg)
    print("Relatório enviado com sucesso!")

if __name__ == "__main__":
    main()
