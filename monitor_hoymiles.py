import os
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

# Link do seu Painel Web no GitHub Pages (ou repositório):
PAINEL_WEB_URL = "https://github.com" 

POTENCIA_INSTALADA_WP = 2000.0  # Potência total dos painéis (Wp)
TARIFA_KWH = 0.88               # Valor da tarifa de energia (R$/kWh)

# Coordenadas Exatas: Vargem Grande Paulista - SP
LATITUDE = -23.6028
LONGITUDE = -47.0258

FUSO_BR = timezone(timedelta(hours=-3))

def carregar_estado():
    if os.path.exists("state.json"):
        try:
            with open("state.json", "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "dia_ativo": False,
        "fechamento_enviado": False,
        "data_atual": "",
        "meta_kwh": 10.0,
        "previsao_desc": "Ensolarado",
        "ultimo_alerta": ""
    }

def salvar_estado(estado):
    try:
        with open("state.json", "w", encoding="utf-8") as f:
            json.dump(estado, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"Erro ao salvar estado: {e}")

def obter_previsao_tempo():
    try:
        url = f"https://api.open-meteo.com/v1/forecast?latitude={LATITUDE}&longitude={LONGITUDE}&daily=weathercode,temperature_2m_max,temperature_2m_min,shortwave_radiation_sum&timezone=America%2FSao_Paulo"
        r = requests.get(url, timeout=10).json()
        daily = r.get("daily", {})
        
        rad_mj = daily.get("shortwave_radiation_sum", [18.0])[0]
        hsp = round(rad_mj / 3.6, 1) # Horas de Sol Pleno (HSP)
        t_max = daily.get("temperature_2m_max", [28])[0]
        t_min = daily.get("temperature_2m_min", [18])[0]
        w_code = daily.get("weathercode", [0])[0]

        condicoes = {
            0: "Céu Limpo / Ensolarado",
            1: "Predomínio de Sol",
            2: "Parcialmente Nublado",
            3: "Nublado",
            45: "Nevoeiro",
            51: "Chuva Leve",
            61: "Chuva Moderada",
            80: "Pancadas de Chuva"
        }
        desc = condicoes.get(w_code, "Sol entre nuvens")
        meta = round((POTENCIA_INSTALADA_WP / 1000.0) * hsp * 0.82, 2)
        if meta < 2.0: meta = 5.0

        return {"desc": desc, "t_max": t_max, "t_min": t_min, "hsp": hsp, "meta_kwh": meta}
    except Exception as e:
        print(f"Aviso previsão Vargem Grande Paulista: {e}")
        return {"desc": "Ensolarado", "t_max": 28, "t_min": 18, "hsp": 5.0, "meta_kwh": 8.5}

def converter_energia(valor):
    if valor is None: return 0.0
    try:
        num = float(str(valor).replace(",", "."))
        if num > 500: return round(num / 1000.0, 2)
        return round(num, 2)
    except Exception: return 0.0

def converter_co2(valor):
    if valor is None: return 0.0
    try:
        num = float(str(valor).replace(",", "."))
        if num > 500: return round(num / 1000.0, 2)
        return round(num, 2)
    except Exception: return 0.0

def extrair_campo(obj, chaves):
    if isinstance(obj, dict):
        for k in chaves:
            if k in obj and obj[k] not in [None, "", "--", "null"]:
                return obj[k]
    return None

def enviar_telegram(mensagem):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": mensagem, "parse_mode": "Markdown"}
    try:
        res = requests.post(url, json=payload, timeout=15)
        print(f"Status Telegram: {res.status_code}")
    except Exception as e:
        print(f"Erro envio Telegram: {e}")

def gerar_painel_html(dados):
    html = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Painel Solar Hoymiles</title>
    <style>
        :root {{ --bg: #0f172a; --card: #1e293b; --text: #f8fafc; --accent: #f59e0b; --green: #10b981; --blue: #3b82f6; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: var(--bg); color: var(--text); margin: 0; padding: 16px; }}
        .container {{ max-width: 700px; margin: 0 auto; }}
        .header {{ text-align: center; padding: 20px 0; }}
        .badge {{ background: rgba(16, 185, 129, 0.2); color: var(--green); padding: 4px 12px; border-radius: 999px; font-weight: bold; font-size: 14px; }}
        .card {{ background: var(--card); border-radius: 16px; padding: 20px; margin-bottom: 16px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.3); }}
        .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }}
        .stat-val {{ font-size: 24px; font-weight: bold; margin-top: 4px; }}
        .progress-bar {{ background: rgba(255,255,255,0.1); height: 10px; border-radius: 5px; overflow: hidden; margin-top: 8px; }}
        .progress-fill {{ background: var(--accent); height: 100%; border-radius: 5px; }}
        .inv-card {{ border-left: 4px solid var(--blue); padding-left: 12px; margin-top: 12px; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>☀️ Usina Solar Hoymiles</h1>
            <span class="badge">{dados['status_str']}</span>
            <p style="color: #94a3b8; margin-top: 8px;">Vargem Grande Paulista - SP | {dados['hora_atual']}</p>
        </div>

        <div class="card">
            <div style="color: #94a3b8;">Potência Instantânea</div>
            <div class="stat-val" style="color: var(--accent); font-size: 36px;">{dados['real_power']} W</div>
            <div style="margin-top: 12px;">Meta Diária: {dados['today_kwh']} / {dados['meta_kwh']} kWh ({dados['pct_meta']}%)</div>
            <div class="progress-bar"><div class="progress-fill" style="width: {min(dados['pct_meta'], 100)}%;"></div></div>
        </div>

        <div class="grid">
            <div class="card">
                <div style="color: #94a3b8;">Gerado Hoje</div>
                <div class="stat-val">{dados['today_kwh']} kWh</div>
                <div style="color: var(--green); margin-top: 4px;">R$ {dados['economia_dia']}</div>
            </div>
            <div class="card">
                <div style="color: #94a3b8;">Mês Atual</div>
                <div class="stat-val">{dados['month_kwh']} kWh</div>
                <div style="color: var(--green); margin-top: 4px;">R$ {dados['economia_mes']}</div>
            </div>
        </div>

        <div class="card">
            <h3>⚡ Telemetria da Rede & Módulos</h3>
            <p>Tensão da Rede: <b>{dados['grid_v']} V</b> | Freq: <b>{dados['grid_f']} Hz</b></p>
            <div>{dados['inv_html']}</div>
        </div>
    </div>
</body>
</html>
"""
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html)

def main():
    agora_br = datetime.now(FUSO_BR)
    hora_int = agora_br.hour
    data_str = agora_br.strftime("%Y-%m-%d")
    hora_str = agora_br.strftime("%d/%m/%Y - %H:%M")

    estado = carregar_estado()
    
    # Novo dia detectado: reseta as travas para aguardar a nova ativação matinal
    if estado.get("data_atual") != data_str:
        estado["data_atual"] = data_str
        estado["dia_ativo"] = False
        estado["fechamento_enviado"] = False
        prev = obter_previsao_tempo()
        estado["meta_kwh"] = prev["meta_kwh"]
        estado["previsao_desc"] = f"{prev['desc']} ({prev['t_min']}°C a {prev['t_max']}°C, {prev['hsp']} HSP)"
        salvar_estado(estado)

    # Coleta Playwright
    captured_data = []
    auth_headers = {}
    station_id = None

    def interceptar_requisicao(request):
        nonlocal auth_headers
        try:
            if "pvm-api" in request.url:
                token = request.headers.get("authorization") or request.headers.get("token")
                if token and len(token) > 15:
                    auth_headers = {"Content-Type": "application/json", "Authorization": token, "token": token}
        except: pass

    def interceptar_resposta(response):
        nonlocal station_id
        try:
            if "application/json" in response.headers.get("content-type", ""):
                d = response.json()
                if isinstance(d, dict):
                    captured_data.append(d)
                    sid = d.get("data", {}).get("id") or d.get("data", {}).get("sid")
                    if sid: station_id = str(sid)
        except: pass

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.on("request", interceptar_requisicao)
        page.on("response", interceptar_resposta)

        try:
            page.goto("https://global.hoymiles.com/website/login", timeout=60000)
            page.wait_for_timeout(2000)
            page.locator("input[type='text'], input[placeholder*='user' i], input[placeholder*='usuário' i]").first.fill(HOYMILES_USER)
            page.locator("input[type='password']").first.fill(HOYMILES_PASS)
            
            cb = page.locator(".el-checkbox__input, input[type='checkbox']").first
            if cb.is_visible(): cb.click()

            page.locator("button[type='submit'], button.el-button--primary, button:has-text('Entrar')").first.click()
            page.wait_for_timeout(10000)

            usina_btn = page.locator(".station-name, .plant-name, .el-table__row, a[href*='overview']").first
            if usina_btn.is_visible():
                usina_btn.click()
                page.wait_for_timeout(5000)

            for tab in ["Dispositivo", "Device", "Equipamento"]:
                el = page.get_by_text(tab, exact=False).first
                if el.is_visible():
                    el.click()
                    page.wait_for_timeout(4000)
                    break
        except Exception as e:
            print(f"Navegação: {e}")
        finally:
            browser.close()

    # Extração de Métricas
    real_power_val = 0.0
    today_eq_raw = None
    month_eq_raw = None
    total_eq_raw = None
    peak_power = 0.0
    co2_raw = None
    grid_v_num = 0.0
    grid_f_num = 60.0
    inversores_dict = {}

    def varrer(obj):
        nonlocal real_power_val, today_eq_raw, month_eq_raw, total_eq_raw, peak_power, co2_raw, grid_v_num, grid_f_num
        if isinstance(obj, dict):
            p = extrair_campo(obj, ["real_power", "realPower", "power"])
            if p and real_power_val == 0.0:
                try: real_power_val = float(str(p).replace(",", "."))
                except: pass

            h = extrair_campo(obj, ["today_eq", "todayEq", "today_energy"])
            if h and today_eq_raw is None: today_eq_raw = h

            m = extrair_campo(obj, ["month_eq", "monthEq"])
            if m and month_eq_raw is None: month_eq_raw = m

            t = extrair_campo(obj, ["total_eq", "totalEq"])
            if t and total_eq_raw is None: total_eq_raw = t

            pk = extrair_campo(obj, ["peak_power", "peakPower"])
            if pk and peak_power == 0.0:
                try: peak_power = float(str(pk).replace(",", "."))
                except: pass

            co2 = extrair_campo(obj, ["co2_emission_reduction", "co2_eq"])
            if co2 and co2_raw is None: co2_raw = co2

            gv = extrair_campo(obj, ["grid_voltage", "gridVoltage", "v_ac", "voltage"])
            if gv and grid_v_num == 0.0:
                try: grid_v_num = float(str(gv).replace(",", "."))
                except: pass

            sn = extrair_campo(obj, ["sn", "mi_sn", "inverter_sn"])
            if sn and str(sn).strip().isdigit() and len(str(sn).strip()) >= 8:
                inversores_dict[str(sn)] = obj

            for v in obj.values(): varrer(v)
        elif isinstance(obj, list):
            for i in obj: varrer(i)

    for item in captured_data: varrer(item)

    today_kwh = converter_energia(today_eq_raw)
    month_kwh = converter_energia(month_eq_raw)
    total_kwh = converter_energia(total_eq_raw)
    co2_kg = converter_co2(co2_raw)

    meta_dia = estado.get("meta_kwh", 10.0)
    pct_meta = round((today_kwh / meta_dia) * 100, 1) if meta_dia > 0 else 0
    economia_dia = round(today_kwh * TARIFA_KWH, 2)
    economia_mes = round(month_kwh * TARIFA_KWH, 2)
    economia_total = round(total_kwh * TARIFA_KWH, 2)
    eficiencia = round((real_power_val / POTENCIA_INSTALADA_WP) * 100, 1) if POTENCIA_INSTALADA_WP > 0 else 0
    hsp = round(today_kwh / (POTENCIA_INSTALADA_WP / 1000.0), 2) if POTENCIA_INSTALADA_WP > 0 else 0

    # Atualiza o Painel HTML (sempre atualizado, mesmo de noite)
    inv_html = ""
    for sn, inv in inversores_dict.items():
        p_inv = inv.get("real_power") or inv.get("power") or "--"
        t_inv = inv.get("temperature") or inv.get("temp") or "--"
        inv_html += f"<div class='inv-card'><b>Inversor {sn}:</b> {p_inv} W | {t_inv}°C</div>"

    status_str = "🟢 Online (Gerando)" if real_power_val > 10 else "🌙 Repouso (Sem Sol)"
    gerar_painel_html({
        "status_str": status_str,
        "hora_atual": hora_str,
        "real_power": real_power_val,
        "today_kwh": today_kwh,
        "meta_kwh": meta_dia,
        "pct_meta": pct_meta,
        "month_kwh": month_kwh,
        "economia_dia": economia_dia,
        "economia_mes": economia_mes,
        "grid_v": grid_v_num or 220.0,
        "grid_f": grid_f_num,
        "inv_html": inv_html or "<p>Microinversores sincronizados via DTU.</p>"
    })

    # ==========================================
    # FLUXO DE NOTIFICAÇÕES TELEGRAM
    # ==========================================

    # 1. ATIVAÇÃO MATINAL (Libera o envio das mensagens de 30 min)
    if (5 <= hora_int <= 10) and real_power_val > 15 and not estado.get("dia_ativo", False):
        estado["dia_ativo"] = True
        estado["fechamento_enviado"] = False
        salvar_estado(estado)

        msg_manha = f"🌅 *USINA ATIVADA — BOM DIA!* ☀️\n"
        msg_manha += f"📅 `{hora_str}` | Vargem Grande Paulista - SP\n\n"
        msg_manha += f"🌤️ *PREVISÃO DO TEMPO*\n"
        msg_manha += f"• {estado.get('previsao_desc')}\n\n"
        msg_manha += f"🎯 *META DE GERAÇÃO PARA HOJE*\n"
        msg_manha += f"• *Meta Estimada:* `{meta_dia:.2f} kWh` (~R$ {meta_dia*TARIFA_KWH:.2f})\n"
        msg_manha += f"• *Status:* 🟢 Monitoramento diurno iniciado\n\n"
        msg_manha += f"🌐 *Painel ao vivo:* {PAINEL_WEB_URL}"
        enviar_telegram(msg_manha)
        return

    # 2. ENCERRAMENTO DO DIA (Bloqueia o envio das mensagens de 30 min até a manhã seguinte)
    if (hora_int >= 17) and real_power_val <= 5 and estado.get("dia_ativo", False) and not estado.get("fechamento_enviado", False):
        estado["dia_ativo"] = False
        estado["fechamento_enviado"] = True
        salvar_estado(estado)

        status_meta = f"🟢 `{pct_meta}% da meta atingida`" if pct_meta >= 100 else f"🟡 `{pct_meta}% da meta atingida`"

        msg_noite = f"🌙 *FIM DA IRRADIAÇÃO SOLAR* 🌙\n"
        msg_noite += f"📅 `{hora_str}` | Usina em Repouso\n\n"
        msg_noite += f"📊 *BALANÇO DO DIA*\n"
        msg_noite += f"• *Gerado Hoje:* `{today_kwh:.2f} kWh`\n"
        msg_noite += f"• *Meta do Dia:* `{meta_dia:.2f} kWh` ({status_meta})\n"
        if peak_power > 0: msg_noite += f"• *Pico Máximo:* `{peak_power:.0f} W`\n"
        msg_noite += f"• *Mês Atual:* `{month_kwh:.2f} kWh`\n\n"
        msg_noite += f"💰 *FINANCEIRO & AMBIENTAL*\n"
        msg_noite += f"• *Economia Hoje:* `R$ {economia_dia:.2f}`\n"
        msg_noite += f"• *Economia no Mês:* `R$ {economia_mes:.2f}`\n"
        msg_noite += f"• *CO₂ Evitado:* `{co2_kg:.2f} kg`\n\n"
        msg_noite += f"🌐 *Painel completo:* {PAINEL_WEB_URL}"
        enviar_telegram(msg_noite)
        return

    # 3. ALERTA DE ANOMALIAS (Notifica apenas se houver problema crítico)
    anomalias = []
    if (8 <= hora_int <= 16) and real_power_val < 10 and estado.get("dia_ativo", False):
        anomalias.append("Usina sem geração em horário de sol pleno.")
    if grid_v_num > 245.0:
        anomalias.append(f"Sobretensão na Rede CA ({grid_v_num:.1f}V > 245V).")
    elif 0 < grid_v_num < 200.0:
        anomalias.append(f"Subtensão na Rede CA ({grid_v_num:.1f}V < 200V).")

    if anomalias and estado.get("ultimo_alerta") != anomalias[0]:
        estado["ultimo_alerta"] = anomalias[0]
        salvar_estado(estado)

        msg_alerta = f"🚨 *ALERTA DE ANOMALIA SOLAR* 🚨\n"
        msg_alerta += f"📅 `{hora_str}`\n\n"
        msg_alerta += f"⚠️ *EVENTO DETECTADO:*\n"
        for a in anomalias: msg_alerta += f"• {a}\n"
        msg_alerta += f"\n📊 *Potência:* `{real_power_val:.1f} W` | *Rede:* `{grid_v_num:.1f} V`\n\n"
        msg_alerta += f"🌐 *Ver detalhes:* {PAINEL_WEB_URL}"
        enviar_telegram(msg_alerta)

    # 4. NOTIFICAÇÃO PADRÃO (A cada 30 min) — SÓ ENVIA SE O DIA ESTIVER ATIVO
    if estado.get("dia_ativo", False) and not estado.get("fechamento_enviado", False):
        status_icon = "🟢 Online (Gerando)" if real_power_val > 10 else "🟡 Baixa Irradiação"
        pico_str = f" | *Pico:* `{peak_power:.0f} W`" if peak_power > 0 else ""

        msg_padrao = f"☀️ *PAINEL SOLAR HOYMILES* ☀️\n"
        msg_padrao += f"📅 `{hora_str}` | {status_icon}\n\n"
        msg_padrao += f"📊 *GERAÇÃO & RENDIMENTO*\n"
        msg_padrao += f"• *Potência Atual:* `{real_power_val:.1f} W` ({eficiencia}% da usina)\n"
        msg_padrao += f"• *Hoje:* `{today_kwh:.2f} kWh`{pico_str}\n"
        msg_padrao += f"• *Rendimento Diário (HSP):* `{hsp:.2f} h`\n"
        msg_padrao += f"• *Mês Atual:* `{month_kwh:.2f} kWh`\n"
        msg_padrao += f"• *Total Histórico:* `{total_kwh:.2f} kWh`\n\n"
        msg_padrao += f"💰 *ECONOMIA ESTIMADA*\n"
        msg_padrao += f"• *Hoje:* `R$ {economia_dia:.2f}`\n"
        msg_padrao += f"• *Mês Atual:* `R$ {economia_mes:.2f}`\n"
        msg_padrao += f"• *Total Acumulado:* `R$ {economia_total:.2f}`\n\n"

        if grid_v_num > 0:
            msg_padrao += f"⚡ *REDE ELÉTRICA (CA)*\n"
            msg_padrao += f"• *Tensão:* `{grid_v_num:.1f} V` | *Frequência:* `{grid_f_num:.1f} Hz`\n\n"

        if inversores_dict:
            msg_padrao += f"🔌 *MICROINVERSORES*\n"
            for idx, (sn, inv) in enumerate(inversores_dict.items(), start=1):
                temp = inv.get("temperature") or inv.get("temp") or "--"
                pot = inv.get("real_power") or inv.get("power") or "--"
                msg_padrao += f"• *Inv {idx} ({sn})*: `{pot} W` | `{temp}°C`\n"
            msg_padrao += "\n"

        msg_padrao += f"🌱 *IMPACTO AMBIENTAL*\n"
        msg_padrao += f"• *CO₂ Evitado:* `{co2_kg:.2f} kg`\n\n"
        msg_padrao += f"🌐 *Painel Web:* {PAINEL_WEB_URL}"

        enviar_telegram(msg_padrao)
    else:
        print("Período noturno/repouso. Painel atualizado silenciosamente sem mensagens no Telegram.")

if __name__ == "__main__":
    main()
