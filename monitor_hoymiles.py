
import json
import re
import requests
from datetime import datetime
from playwright.sync_api import sync_playwright

# ==========================================
# CONFIGURAÇÕES E CREDENCIAIS
# ==========================================
HOYMILES_USER = "renato93@gmail.com"
HOYMILES_PASS = "mcosta295@"

TELEGRAM_BOT_TOKEN = "8946039720:AAF7U0QokemhGv_5iTzVj9L6IGB1C1kOvhE"
TELEGRAM_CHAT_ID = "1020154663"

POTENCIA_INSTALADA_WP = 2000.0  # Potência total dos painéis (Wp)
TARIFA_KWH = 0.88               # Valor da tarifa de energia (R$/kWh)

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
        # Se vier em gramas (ex: 74337 g -> 74.34 kg)
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
    print("Iniciando coleta detalhada Playwright...")

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

            # 2. Entrar na visão da Usina
            usina_btn = page.locator(".station-name, .plant-name, .table-row, a[href*='overview']").first
            if usina_btn.is_visible():
                usina_btn.click()
                page.wait_for_timeout(6000)

            # 3. Navegar para a aba de Dispositivos / Equipamentos
            dispositivo_btn = page.locator("text='Dispositivo', text='Device', text='Equipamento', .el-menu-item:has-text('Dispositivo')").first
            if dispositivo_btn.is_visible():
                dispositivo_btn.click()
                page.wait_for_timeout(7000)
                page.wait_for_load_state("networkidle")

        except Exception as e:
            print(f"Aviso navegação: {e}")
        finally:
            browser.close()

    # Variáveis consolidadas
    real_power_val = 0.0
    today_eq_raw = None
    month_eq_raw = None
    year_eq_raw = None
    total_eq_raw = None
    peak_power = 0.0
    co2_raw = None
    grid_v = "--"
    grid_f = "--"
    grid_i = "--"
    power_factor = "--"
    dtu_signal = "--"
    last_sync = "--"
    alarmes_detectados = []
    inversores_info = []

    def varrer_json(obj):
        nonlocal real_power_val, today_eq_raw, month_eq_raw, year_eq_raw, total_eq_raw
        nonlocal peak_power, co2_raw, grid_v, grid_f, grid_i, power_factor, dtu_signal, last_sync
        
        if isinstance(obj, dict):
            # Potência e Geração
            p = extrair_campo(obj, ["real_power", "realPower", "pac", "power", "real_p"])
            if p is not None and real_power_val == 0.0:
                try: real_power_val = float(str(p).replace(",", "."))
                except: pass

            h = extrair_campo(obj, ["today_eq", "todayEq", "today_energy", "e_today"])
            if h is not None and today_eq_raw is None: today_eq_raw = h

            m = extrair_campo(obj, ["month_eq", "monthEq", "month_energy", "e_month"])
            if m is not None and month_eq_raw is None: month_eq_raw = m

            y = extrair_campo(obj, ["year_eq", "yearEq", "year_energy", "e_year"])
            if y is not None and year_eq_raw is None: year_eq_raw = y

            t = extrair_campo(obj, ["total_eq", "totalEq", "total_energy", "e_total"])
            if t is not None and total_eq_raw is None: total_eq_raw = t

            pk = extrair_campo(obj, ["peak_power", "peakPower", "max_power"])
            if pk is not None and peak_power == 0.0:
                try: peak_power = float(str(pk).replace(",", "."))
                except: pass

            co2 = extrair_campo(obj, ["co2_emission_reduction", "co2_eq", "co2_reduction"])
            if co2 is not None and co2_raw is None: co2_raw = co2

            # Rede CA
            gv = extrair_campo(obj, ["grid_voltage", "gridVoltage", "v_ac", "vac", "voltage"])
            if gv is not None and grid_v == "--": grid_v = str(gv)

            gf = extrair_campo(obj, ["grid_frequency", "gridFrequency", "frequency", "fac", "freq"])
            if gf is not None and grid_f == "--": grid_f = str(gf)

            gi = extrair_campo(obj, ["grid_current", "gridCurrent", "i_ac", "iac", "current"])
            if gi is not None and grid_i == "--": grid_i = str(gi)

            pf = extrair_campo(obj, ["power_factor", "powerFactor", "cos_phi", "pf"])
            if pf is not None and power_factor == "--": power_factor = str(pf)

            # DTU / Comunicação
            sig = extrair_campo(obj, ["csq", "signal", "rssi", "dtu_rssi", "link_status"])
            if sig is not None and dtu_signal == "--": dtu_signal = f"{sig}%"

            sync = extrair_campo(obj, ["last_upload_time", "upload_time", "report_time", "update_time"])
            if sync is not None and last_sync == "--":
                last_sync = str(sync).split(" ")[-1] if " " in str(sync) else str(sync)

            # Alarmes
            al = extrair_campo(obj, ["warn_list", "alarm_list", "alarm_code", "alarms"])
            if al and isinstance(al, list):
                for item_al in al:
                    if item_al and str(item_al) not in alarmes_detectados:
                        alarmes_detectados.append(str(item_al))

            # Dispositivos
            if "sn" in obj or "mi_sn" in obj:
                inversores_info.append(obj)

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
    year_kwh = converter_energia(year_eq_raw)
    total_kwh = converter_energia(total_eq_raw)

    eficiencia = round((real_power_val / POTENCIA_INSTALADA_WP) * 100, 1) if POTENCIA_INSTALADA_WP > 0 else 0
    hsp = round(today_kwh / (POTENCIA_INSTALADA_WP / 1000.0), 2) if POTENCIA_INSTALADA_WP > 0 else 0

    economia_dia = round(today_kwh * TARIFA_KWH, 2)
    economia_mes = round(month_kwh * TARIFA_KWH, 2)
    economia_total = round(total_kwh * TARIFA_KWH, 2)

    # CO2 corrigido
    co2_evitado = converter_co2(co2_raw)
    if co2_evitado == 0.0 and today_kwh > 0:
        co2_evitado = round(total_kwh * 0.42, 2)
    arvores_equiv = round(co2_evitado / 20.0, 2)

    status_icon = "🟢 Online (Gerando)" if real_power_val > 10 else "🌙 Offline / Repouso"
    agora = datetime.now().strftime("%d/%m/%Y - %H:%M")

    # Montagem da Mensagem
    msg = f"☀️ *PAINEL SOLAR HOYMILES* ☀️\n"
    msg += f"📅 `{agora}` | {status_icon}\n\n"

    msg += f"📊 *GERAÇÃO & RENDIMENTO*\n"
    msg += f"• *Potência Atual:* `{real_power_val:.1f} W` ({eficiencia}% da usina)\n"
    msg += f"• *Hoje:* `{today_kwh:.2f} kWh`"
    if peak_power > 0: msg += f" | *Pico:* `{peak_power:.0f} W`\n"
    else: msg += "\n"
    msg += f"• *Rendimento Diário (HSP):* `{hsp:.2f} h`\n"
    msg += f"• *Mês Atual:* `{month_kwh:.2f} kWh`\n"
    if year_kwh > 0 and year_kwh != total_kwh:
        msg += f"• *Ano Atual:* `{year_kwh:.2f} kWh`\n"
    msg += f"• *Total Histórico:* `{total_kwh:.2f} kWh`\n\n"

    msg += f"💰 *ECONOMIA ESTIMADA*\n"
    msg += f"• *Hoje:* `R$ {economia_dia:.2f}`\n"
    msg += f"• *Mês Atual:* `R$ {economia_mes:.2f}`\n"
    msg += f"• *Total Acumulado:* `R$ {economia_total:.2f}`\n\n"

    if grid_v != "--" or grid_f != "--":
        msg += f"⚡ *REDE ELÉTRICA (CA)*\n"
        msg += f"• *Tensão:* `{grid_v} V` | *Frequência:* `{grid_f} Hz`\n"
        if grid_i != "--" or power_factor != "--":
            msg += f"• *Corrente CA:* `{grid_i} A` | *Fator Potência:* `{power_factor}`\n"
        msg += "\n"

    if inversores_info:
        msg += f"🔌 *MICROINVERSORES & PLACAS*\n"
        vistos = set()
        for idx, inv in enumerate(inversores_info, start=1):
            sn = inv.get("sn") or inv.get("mi_sn") or f"Inversor {idx}"
            if sn in vistos: continue
            vistos.add(sn)

            temp = inv.get("temperature") or inv.get("temp") or "--"
            pot = inv.get("real_power") or inv.get("realPower") or inv.get("power") or "--"
            
            # Se tensão foi capturada no microinversor
            v_inv = inv.get("grid_voltage") or inv.get("gridVoltage") or "--"
            
            msg += f"• *{sn}:* `{pot} W` | `{temp}°C`"
            if v_inv != "--": msg += f" | `{v_inv} V`\n"
            else: msg += "\n"

            # Canais DC individuais (PV1, PV2...)
            ports = inv.get("port_list") or inv.get("channels") or inv.get("pv_list")
            if ports and isinstance(ports, list):
                for p_idx, port in enumerate(ports, start=1):
                    p_w = port.get("power") or port.get("real_power") or "--"
                    p_v = port.get("voltage") or port.get("v_dc") or "--"
                    p_i = port.get("current") or port.get("i_dc") or "--"
                    msg += f"  └ PV{p_idx}: `{p_v} V` | `{p_i} A` | `{p_w} W`\n"
        msg += "\n"

    msg += f"📡 *HARDWARE & DIAGNÓSTICO*\n"
    if dtu_signal != "--" or last_sync != "--":
        msg += f"• *DTU Wi-Fi:* `{dtu_signal}` | *Último Sync:* `{last_sync}`\n"
    
    if alarmes_detectados:
        msg += f"• *Alarmes:* ⚠️ `{' | '.join(alarmes_detectados)}`\n\n"
    else:
        msg += f"• *Alarmes:* 🟢 Nenhum alarme ativo\n\n"

    msg += f"🌱 *IMPACTO AMBIENTAL*\n"
    msg += f"• *CO₂ Total Evitado:* `{co2_evitado:.2f} kg` (~{arvores_equiv} árvores)"

    enviar_telegram(msg)
    print("Relatório completo enviado com sucesso!")

if __name__ == "__main__":
    main()
