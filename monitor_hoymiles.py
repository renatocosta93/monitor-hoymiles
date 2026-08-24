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

POTENCIA_INSTALADA_WP = 2000.0  # Potência total instalada (Wp)
TARIFA_KWH = 0.88               # Tarifa de energia (R$/kWh)

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
            if k in obj and obj[k] not in [None, "", "--", "null"]:
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
    print("Iniciando monitoramento Hoymiles...")
    captured_data = []
    auth_headers = {}
    station_id = None

    def interceptar_requisicao(request):
        nonlocal auth_headers
        try:
            if "pvm-api" in request.url or "hoymiles" in request.url:
                headers = request.headers
                token = headers.get("authorization") or headers.get("token") or headers.get("x-access-token")
                if token and len(token) > 15:
                    auth_headers = {
                        "Content-Type": "application/json",
                        "Accept": "application/json, text/plain, */*",
                        "Authorization": token,
                        "token": token,
                        "User-Agent": headers.get("user-agent", "Mozilla/5.0"),
                        "Origin": "https://global.hoymiles.com",
                        "Referer": "https://global.hoymiles.com/website/login"
                    }
        except Exception:
            pass

    def interceptar_resposta(response):
        nonlocal station_id
        try:
            if "application/json" in response.headers.get("content-type", ""):
                data = response.json()
                if isinstance(data, dict):
                    captured_data.append(data)
                    # Busca o ID da Usina
                    d = data.get("data", {})
                    if isinstance(d, dict):
                        sid = d.get("id") or d.get("sid") or d.get("station_id")
                        if sid and not station_id: station_id = str(sid)
                    elif isinstance(d, list) and len(d) > 0 and isinstance(d[0], dict):
                        sid = d[0].get("id") or d[0].get("sid")
                        if sid and not station_id: station_id = str(sid)
        except Exception:
            pass

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            viewport={"width": 1440, "height": 900}
        )
        page = context.new_page()
        page.on("request", interceptar_requisicao)
        page.on("response", interceptar_resposta)

        try:
            print("1. Efetuando Login...")
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

            # 2. Abre a usina
            print("2. Acessando painel da Usina...")
            usina_btn = page.locator(".station-name, .plant-name, .el-table__row, a[href*='overview']").first
            if usina_btn.is_visible():
                usina_btn.click()
                page.wait_for_timeout(6000)
                page.wait_for_load_state("networkidle")

            # Identifica SID da URL caso não capturado
            if not station_id:
                url_match = re.search(r'[?&]id=(\d+)', page.url)
                if url_match: station_id = url_match.group(1)

            # 3. Navega para a aba de Dispositivos e expande os microinversores
            print("3. Carregando dispositivos e componentes...")
            for tab_txt in ["Dispositivo", "Dispositivos", "Device", "Devices", "Equipamento", "Layout"]:
                try:
                    tab = page.get_by_text(tab_txt, exact=False).first
                    if tab.is_visible():
                        tab.click()
                        page.wait_for_timeout(5000)
                        page.wait_for_load_state("networkidle")
                        
                        # Clica nos botões de expansão da tabela para abrir detalhes de portas PV1/PV2
                        expand_icons = page.locator(".el-table__expand-icon, .el-icon-arrow-right").all()
                        for icon in expand_icons[:5]:
                            try: icon.click()
                            except: pass
                        page.wait_for_timeout(3000)
                        break
                except Exception:
                    pass

        except Exception as e:
            print(f"Aviso navegação Playwright: {e}")
        finally:
            browser.close()

    # 4. Requisições complementares diretas via API com os cabeçalhos autenticados
    if auth_headers:
        print("4. Coletando telemetria avançada via API...")
        endpoints = [
            ("https://global.hoymiles.com/pvm-api/dev/select_mi", {"sid": station_id, "page": 1, "page_size": 50}),
            ("https://global.hoymiles.com/pvm-api/dev/find_mi_real_data", {"sid": station_id}),
            ("https://global.hoymiles.com/pvm-api/dev/select_dtu", {"sid": station_id, "page": 1, "page_size": 50}),
            ("https://global.hoymiles.com/pvm-api/station/find_power_chart", {"sid": station_id, "time": datetime.now(FUSO_BR).strftime("%Y-%m-%d")}),
            ("https://global.hoymiles.com/pvm-api/alarm/select_warn", {"sid": station_id, "page": 1, "page_size": 20})
        ]
        for url, payload in endpoints:
            try:
                r = requests.post(url, json=payload, headers=auth_headers, timeout=10)
                if r.status_code == 200:
                    j = r.json()
                    if isinstance(j, dict):
                        captured_data.append(j)
            except Exception:
                pass

    # ==========================================
    # PROCESSAMENTO E EXTRAÇÃO DOS DADOS
    # ==========================================
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
            # Potência Instantânea e Geração
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

            # Extração da Curva Diária (Início de Geração e Pico Real)
            chart_list = extrair_campo(obj, ["chart_list", "power_list", "points", "detail", "list"])
            if chart_list and isinstance(chart_list, list):
                for pt in chart_list:
                    if isinstance(pt, dict) and ("val" in pt or "power" in pt):
                        val_num = float(str(pt.get("val") or pt.get("power") or 0).replace(",", "."))
                        time_val = str(pt.get("time") or pt.get("date") or "")
                        if val_num > 10 and not start_time_str and time_val:
                            start_time_str = time_val.split(" ")[-1][:5]
                        if val_num > peak_power:
                            peak_power = val_num

            # Tensão e Frequência CA
            gv = extrair_campo(obj, ["grid_voltage", "gridVoltage", "v_ac", "vac", "voltage", "vol"])
            if gv is not None and grid_v == "--": grid_v = str(gv)

            gf = extrair_campo(obj, ["grid_frequency", "gridFrequency", "frequency", "fac", "freq"])
            if gf is not None and grid_f == "--": grid_f = str(gf)

            # DTU & Sincronismo
            sig = extrair_campo(obj, ["csq", "signal", "rssi", "dtu_rssi", "link_status"])
            if sig is not None and dtu_signal == "--": dtu_signal = f"{sig}%"

            sync = extrair_campo(obj, ["last_upload_time", "upload_time", "report_time", "update_time"])
            if sync is not None and last_sync == "--":
                last_sync = str(sync).split(" ")[-1][:5] if " " in str(sync) else str(sync)[:5]

            # Alarmes
            al = extrair_campo(obj, ["warn_list", "alarm_list", "alarm_code", "alarms"])
            if al and isinstance(al, list):
                for item_al in al:
                    if item_al and str(item_al) not in alarmes_detectados:
                        alarmes_detectados.append(str(item_al))

            # Detecção de Microinversores
            sn = extrair_campo(obj, ["sn", "mi_sn", "inverter_sn", "device_sn", "miSn"])
            if sn and str(sn).strip() != "" and len(str(sn).strip()) >= 6:
                sn_str = str(sn).strip()
                if not any(ign in sn_str.lower() for ign in ["station", "plant", "dtu"]):
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

    if total_eq_raw is None and today_eq_raw is None:
        print("Sessão não sincronizada. Envio abortado para evitar mensagem vazia.")
        return

    # Cálculos Consolidados
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

    # ==========================================
    # MONTAGEM DO PAINEL TELEGRAM
    # ==========================================
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

    # Tensão da rede (obtém do inversor caso não esteja na raiz)
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

    # Microinversores & Placas DC
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

            # Busca canais PV em formato aninhado ou em chaves planas (p1/u1/i1, pv1_power...)
            portas_encontradas = []
            ports_raw = inv.get("port_list") or inv.get("channels") or inv.get("pv_list") or inv.get("portList")
            
            if ports_raw and isinstance(ports_raw, list):
                for p_idx, port in enumerate(ports_raw, start=1):
                    p_w = port.get("power") or port.get("real_power") or port.get("realPower") or "--"
                    p_v = port.get("voltage") or port.get("v_dc") or port.get("vol") or "--"
                    p_i = port.get("current") or port.get("i_dc") or port.get("cur") or "--"
                    portas_encontradas.append((p_idx, p_v, p_i, p_w))
            else:
                # Verificação de campos planos
                for i in range(1, 5):
                    pw = inv.get(f"pv{i}_power") or inv.get(f"p{i}") or inv.get(f"power{i}")
                    pv = inv.get(f"pv{i}_vol") or inv.get(f"u{i}") or inv.get(f"vol{i}")
                    pi = inv.get(f"pv{i}_cur") or inv.get(f"i{i}") or inv.get(f"cur{i}")
                    if pw is not None or pv is not None:
                        portas_encontradas.append((i, pv or "--", pi or "--", pw or "--"))

            if portas_encontradas:
                total_p = len(portas_encontradas)
                for p_idx, (num_p, p_v, p_i, p_w) in enumerate(portas_encontradas, start=1):
                    prefix = "└" if p_idx == total_p else "├"
                    msg += f"  {prefix} PV{num_p}: `{p_v} V` | `{p_i} A` | `{p_w} W`\n"
        msg += "\n"

    # Hardware & Diagnóstico
    msg += f"📡 *HARDWARE & DIAGNÓSTICO*\n"
    if dtu_signal != "--" or last_sync != "--":
        msg += f"• *DTU Wi-Fi:* `{dtu_signal}` | *Último Sync:* `{last_sync}`\n"
    
    if alarmes_detectados:
        msg += f"• *Alarmes:* ⚠️ `{' | '.join(alarmes_detectados)}`\n\n"
    else:
        msg += f"• *Alarmes:* 🟢 Nenhum alarme ativo\n\n"

    # Ambiental
    msg += f"🌱 *IMPACTO AMBIENTAL*\n"
    msg += f"• *CO₂ Total Evitado:* `{co2_evitado:.2f} kg` (~{arvores_equiv} árvores)"

    enviar_telegram(msg)
    print("Processo concluído com sucesso!")

if __name__ == "__main__":
    main()
