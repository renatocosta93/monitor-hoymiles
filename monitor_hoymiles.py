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

POTENCIA_INSTALADA_WP = 2000.0  # Potência total dos módulos instalados (em Wp)
TARIFA_KWH = 0.88               # Valor médio da sua tarifa de energia (R$/kWh)

# Fuso Horário de Brasília (UTC-3)
FUSO_BR = timezone(timedelta(hours=-3))

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
    print("Iniciando coleta avançada Playwright...")
    captured_data = []
    auth_token = None
    captured_sid = None

    def interceptar_resposta(response):
        nonlocal auth_token, captured_sid
        try:
            # Captura token nos headers de envio
            req_headers = response.request.headers
            token = req_headers.get("authorization") or req_headers.get("token")
            if token and len(token) > 20 and not auth_token:
                auth_token = token

            if "application/json" in response.headers.get("content-type", ""):
                data = response.json()
                if isinstance(data, dict):
                    captured_data.append(data)
                    # Procura o SID da usina
                    d = data.get("data", {})
                    if isinstance(d, dict):
                        sid = d.get("id") or d.get("sid") or d.get("station_id")
                        if sid and not captured_sid:
                            captured_sid = sid
                    elif isinstance(d, list) and len(d) > 0 and isinstance(d[0], dict):
                        sid = d[0].get("id") or d[0].get("sid")
                        if sid and not captured_sid:
                            captured_sid = sid
        except Exception:
            pass

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            viewport={"width": 1440, "height": 900}
        )
        page = context.new_page()
        page.on("response", interceptar_resposta)

        try:
            print("1. Realizando login...")
            page.goto("https://global.hoymiles.com/website/login", wait_until="networkidle", timeout=60000)
            page.wait_for_timeout(2000)

            page.locator("input[type='text'], input[placeholder*='usuário' i], input[placeholder*='user' i], input[placeholder*='account' i]").first.fill(HOYMILES_USER)
            page.locator("input[type='password']").first.fill(HOYMILES_PASS)

            checkbox = page.locator(".el-checkbox__input, input[type='checkbox']").first
            if checkbox.is_visible():
                checkbox.click()

            page.locator("button[type='submit'], button.el-button--primary, button:has-text('Entrar'), button:has-text('Login')").first.click()

            page.wait_for_selector(".station-name, .plant-name, .el-table__row, a[href*='overview']", timeout=25000)
            page.wait_for_timeout(4000)

            print("2. Acessando usina...")
            usina_btn = page.locator(".station-name, .plant-name, .el-table__row, a[href*='overview']").first
            if usina_btn.is_visible():
                usina_btn.click()
                page.wait_for_timeout(6000)
                page.wait_for_load_state("networkidle")

            # 3. Clica especificamente na aba de Dispositivos para carregar microinversores
            print("3. Abrindo dispositivos...")
            for tab_txt in ["Dispositivo", "Dispositivos", "Device", "Devices", "Equipamento", "Layout"]:
                try:
                    tab = page.get_by_text(tab_txt, exact=False).first
                    if tab.is_visible():
                        tab.click()
                        page.wait_for_timeout(5000)
                        page.wait_for_load_state("networkidle")
                        break
                except Exception:
                    pass

            # 4. Requisições diretas à API usando a sessão do navegador
            js_script = """
            async () => {
                let token = localStorage.getItem('token') || localStorage.getItem('access_token') || sessionStorage.getItem('token') || '';
                let sid = localStorage.getItem('sid') || localStorage.getItem('station_id') || '';
                let results = [];
                let headers = {
                    'Content-Type': 'application/json',
                    'Authorization': token,
                    'token': token
                };
                
                let urls = [
                    {url: '/pvm-api/dev/select_mi', body: {sid: sid, page: 1, page_size: 50}},
                    {url: '/pvm-api/dev/select_dtu', body: {sid: sid}},
                    {url: '/pvm-api/station/find_power_chart', body: {sid: sid}},
                    {url: '/pvm-api/alarm/select_warn', body: {sid: sid, page: 1, page_size: 20}}
                ];
                
                for(let item of urls) {
                    try {
                        let res = await fetch(item.url, {
                            method: 'POST',
                            headers: headers,
                            body: JSON.stringify(item.body)
                        });
                        let j = await res.json();
                        results.push(j);
                    } catch(e) {}
                }
                return results;
            }
            """
            extra_res = page.evaluate(js_script)
            if extra_res and isinstance(extra_res, list):
                for item in extra_res:
                    if isinstance(item, dict):
                        captured_data.append(item)

        except Exception as e:
            print(f"Aviso Playwright: {e}")
        finally:
            browser.close()

    # Variáveis consolidadas
    real_power_val = None
    today_eq_raw = None
    month_eq_raw = None
    total_eq_raw = None
    peak_power = 0.0
    co2_raw = None
    start_time_str = None
    grid_v = "--"
    grid_f = "--"
    dtu_signal = "--"
    last_sync = "--"
    alarmes_detectados = []
    inversores_dict = {}

    def varrer_json(obj):
        nonlocal real_power_val, today_eq_raw, month_eq_raw, total_eq_raw
        nonlocal peak_power, co2_raw, start_time_str, grid_v, grid_f, dtu_signal, last_sync
        
        if isinstance(obj, dict):
            # Potência e Energia
            p = extrair_campo(obj, ["real_power", "realPower", "pac", "power", "real_p"])
            if p is not None and real_power_val is None:
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

            # Extração da hora de início e pico pela curva solar (power_chart)
            chart_list = extrair_campo(obj, ["chart_list", "power_list", "points", "detail"])
            if chart_list and isinstance(chart_list, list):
                for pt in chart_list:
                    if isinstance(pt, dict):
                        p_val = float(str(pt.get("val") or pt.get("power") or 0).replace(",", "."))
                        p_time = str(pt.get("time") or pt.get("date") or "")
                        if p_val > 10 and not start_time_str and p_time:
                            start_time_str = p_time.split(" ")[-1][:5]
                        if p_val > peak_power:
                            peak_power = p_val

            # Rede Elétrica
            gv = extrair_campo(obj, ["grid_voltage", "gridVoltage", "v_ac", "vac", "voltage", "vol"])
            if gv is not None and grid_v == "--": grid_v = str(gv)

            gf = extrair_campo(obj, ["grid_frequency", "gridFrequency", "frequency", "fac", "freq"])
            if gf is not None and grid_f == "--": grid_f = str(gf)

            # DTU
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

            # Microinversores
            sn = extrair_campo(obj, ["sn", "mi_sn", "inverter_sn", "device_sn", "miSn"])
            if sn and str(sn).strip() != "" and len(str(sn).strip()) >= 8:
                sn_str = str(sn).strip()
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
        varrer_json(item)

    # Validação de integridade
    if total_eq_raw is None and today_eq_raw is None:
        print("Sessão não sincronizada a tempo. Abortando envio para evitar dados vazios.")
        return

    real_power_val = real_power_val if real_power_val is not None else 0.0
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

    inicio_str = f" | 🌅 *Início:* `{start_time_str}`" if start_time_str else ""
    pico_str = f" | *Pico:* `{peak_power:.0f} W`" if peak_power > 0 else ""

    agora_br = datetime.now(FUSO_BR).strftime("%d/%m/%Y - %H:%M")
    status_icon = "🟢 Online (Gerando)" if real_power_val > 10 else "🌙 Offline / Repouso"

    # Montagem da Mensagem
    msg = f"☀️ *PAINEL SOLAR HOYMILES* ☀️\n"
    msg += f"📅 `{agora_br}` | {status_icon}\n\n"

    msg += f"📊 *GERAÇÃO & RENDIMENTO*\n"
    msg += f"• *Potência Atual:* `{real_power_val:.1f} W` ({eficiencia}% da usina)\n"
    msg += f"• *Hoje:* `{today_kwh:.2f} kWh`{pico_str}\n"
    msg += f"• *Rendimento Diário (HSP):* `{hsp:.2f} h`{inicio_str}\n"
    msg += f"• *Mês Atual:* `{month_kwh:.2f} kWh`\n"
    msg += f"• *Total Histórico:* `{total_kwh:.2f} kWh`\n\n"

    msg += f"💰 *ECONOMIA ESTIMADA*\n"
    msg += f"• *Hoje:* `R$ {economia_dia:.2f}`\n"
    msg += f"• *Mês Atual:* `R$ {economia_mes:.2f}`\n"
    msg += f"• *Total Acumulado:* `R$ {economia_total:.2f}`\n\n"

    # Se a tensão não estiver no sumário geral, pega do primeiro microinversor
    if grid_v == "--" and inversores_dict:
        for inv in inversores_dict.values():
            v_cand = extrair_campo(inv, ["grid_voltage", "gridVoltage", "v_ac", "vac", "voltage", "vol"])
            if v_cand:
                grid_v = str(v_cand)
                break

    if grid_v != "--" or grid_f != "--":
        msg += f"⚡ *REDE ELÉTRICA (CA)*\n"
        msg += f"• *Tensão:* `{grid_v} V`"
        if grid_f != "--": msg += f" | *Frequência:* `{grid_f} Hz`"
        msg += "\n\n"

    if inversores_dict:
        msg += f"🔌 *MICROINVERSORES & PLACAS (DC)*\n"
        for idx, (sn, inv) in enumerate(inversores_dict.items(), start=1):
            temp = inv.get("temperature") or inv.get("temp") or "--"
            pot = inv.get("real_power") or inv.get("realPower") or inv.get("power") or "--"
            v_inv = inv.get("grid_voltage") or inv.get("gridVoltage") or grid_v

            detalhes = []
            if pot != "--": detalhes.append(f"{pot} W")
            if temp != "--": detalhes.append(f"{temp}°C")
            if v_inv != "--": detalhes.append(f"{v_inv} V")

            msg += f"• *Inv {idx} ({sn})* — `{' | '.join(detalhes)}`\n"

            ports = inv.get("port_list") or inv.get("channels") or inv.get("pv_list") or inv.get("portList")
            if ports and isinstance(ports, list):
                total_p = len(ports)
                for p_idx, port in enumerate(ports, start=1):
                    prefix = "└" if p_idx == total_p else "├"
                    p_w = port.get("power") or port.get("real_power") or port.get("realPower") or "--"
                    p_v = port.get("voltage") or port.get("v_dc") or port.get("vol") or "--"
                    p_i = port.get("current") or port.get("i_dc") or port.get("cur") or "--"
                    msg += f"  {prefix} PV{p_idx}: `{p_v} V` | `{p_i} A` | `{p_w} W`\n"
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
    print("Processo concluído com sucesso!")

if __name__ == "__main__":
    main()
