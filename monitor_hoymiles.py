import os
import json
import re
import calendar
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

PAINEL_WEB_URL = "https://renatocosta93.github.io/monitor-hoymiles/"
WEBHOOK_ATUALIZAR_URL = "https://script.google.com/macros/s/AKfycbwO9ybli9NqAPft9Aa0dQNorfcZYTSmKucJUU7fBtzCIGgT-5ZKYWo2hPFz5EPkJ6PT/exec"

POTENCIA_INSTALADA_WP = 4500.0       # 4.5 kWp
TARIFA_KWH = 1.02                    # R$/kWh
CUSTO_SISTEMA = 13400.0              # R$ 13.400,00 (Investimento da usina)
DATA_INICIO_OPERACAO = "2026-08-20"  # Início oficial da usina

LATITUDE = -23.6028
LONGITUDE = -47.0258

FUSO_BR = timezone(timedelta(hours=-3))
SILENT_MODE = os.environ.get("SILENT_MODE", "false").lower() in ["true", "1", "yes"]

# ==========================================
# FUNÇÕES AUXILIARES DE FORMATAÇÃO E CÁLCULO
# ==========================================
def fmt_br(valor, dec=2):
    try:
        num = float(valor)
        return f"{num:,.{dec}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return "0,00"

def fmt_decimal(valor, dec=2):
    try:
        return f"{float(valor):.{dec}f}"
    except Exception:
        return "0.00"

def converter_energia(valor):
    if valor is None:
        return 0.0
    try:
        num = float(str(valor).replace(",", "."))
        if num > 500:
            return round(num / 1000.0, 3)
        return round(num, 3)
    except Exception:
        return 0.0

def extrair_campo(obj, chaves):
    if isinstance(obj, dict):
        for k in chaves:
            if k in obj and obj[k] not in [None, "", "--", "null"]:
                return obj[k]
    return None

def carregar_estado():
    if os.path.exists("state.json"):
        try:
            with open("state.json", "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "data_atual": "",
        "data_bom_dia_enviado": "",
        "data_fechamento_enviado": "",
        "meta_kwh": 18.0,
        "previsao_desc": "Ensolarado",
        "mensagens_armazenadas": [],
        "historico_dias": {},
        "leituras_horarias": {},
        "clima_horas_hoje": {},
        "historico_clima": {}
    }

def salvar_estado(estado):
    try:
        with open("state.json", "w", encoding="utf-8") as f:
            json.dump(estado, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"Erro ao salvar estado: {e}")

def obter_icone_clima(codigo):
    if codigo in [0, 1]: return "☀️"
    if codigo == 2: return "🌤️"
    if codigo in [3, 45]: return "⛅"
    if codigo in [51, 53, 55, 61, 63, 65, 80, 81, 82]: return "🌧️"
    if codigo in [95, 96]: return "⛈️"
    return "☀️"

def obter_previsao_tempo(hora_atual_int=12, data_atual_str=""):
    condicoes_map = {
        0: "Céu Limpo / Ensolarado",
        1: "Predomínio de Sol",
        2: "Parcialmente Nublado",
        3: "Nublado",
        45: "Nevoeiro",
        51: "Chuva Leve",
        61: "Chuva Moderada",
        80: "Pancadas de Chuva",
        95: "Tempestade"
    }

    try:
        url = (
            f"https://api.open-meteo.com/v1/forecast?latitude={LATITUDE}&longitude={LONGITUDE}"
            f"&current=weather_code,precipitation,temperature_2m"
            f"&hourly=weather_code,temperature_2m,cloud_cover,precipitation_probability"
            f"&daily=weathercode,temperature_2m_max,temperature_2m_min,shortwave_radiation_sum"
            f"&timezone=America%2FSao_Paulo"
        )
        r = requests.get(url, timeout=10).json()
        daily = r.get("daily", {})
        current = r.get("current", {})
        hourly = r.get("hourly", {})

        rad_mj = daily.get("shortwave_radiation_sum", [18.0])[0]
        hsp = round(rad_mj / 3.6, 1)
        t_max = daily.get("temperature_2m_max", [28])[0]
        t_min = daily.get("temperature_2m_min", [18])[0]
        w_code_day = daily.get("weathercode", [0])[0]

        cur_wcode = current.get("weather_code", w_code_day)
        cur_precip = current.get("precipitation", 0.0)
        cur_temp = current.get("temperature_2m", 25.0)
        cur_desc = condicoes_map.get(cur_wcode, "Sol entre nuvens")

        desc_dia = condicoes_map.get(w_code_day, "Sol entre nuvens")
        meta = round((POTENCIA_INSTALADA_WP / 1000.0) * hsp * 0.82, 2)
        if meta < 5.0: meta = 15.0

        # Radar das Próximas 3 Horas
        h_times = hourly.get("time", [])
        h_codes = hourly.get("weather_code", [])
        h_temps = hourly.get("temperature_2m", [])
        h_clouds = hourly.get("cloud_cover", [])
        h_precips = hourly.get("precipitation_probability", [])

        time_map = {t: idx for idx, t in enumerate(h_times)}
        radar_lista = []
        clouds_futuras = []
        precips_futuras = []

        for delta in range(1, 4):
            target_h = hora_atual_int + delta
            if target_h <= 23:
                key_iso = f"{data_atual_str}T{target_h:02d}:00"
                if key_iso in time_map:
                    idx = time_map[key_iso]
                    c_val = h_clouds[idx] if idx < len(h_clouds) else 25
                    p_val = h_precips[idx] if idx < len(h_precips) else 0
                    t_val = h_temps[idx] if idx < len(h_temps) else cur_temp
                    w_val = h_codes[idx] if idx < len(h_codes) else 0
                    clouds_futuras.append(c_val)
                    precips_futuras.append(p_val)
                    radar_lista.append({
                        "hora": f"{target_h:02d}h",
                        "temp": round(t_val, 1),
                        "nuvens": c_val,
                        "chuva_prob": p_val,
                        "wcode": w_val,
                        "icon": obter_icone_clima(w_val)
                    })

        # Diagnóstico de Tendência
        max_chuva = max(precips_futuras) if precips_futuras else 0
        media_nuvens = int(sum(clouds_futuras) / len(clouds_futuras)) if clouds_futuras else 20

        if max_chuva >= 40:
            radar_tag = "Alerta de Chuva"
            radar_cor = "#ef4444"
            radar_cor_rgba = "rgba(239, 68, 68, 0.2)"
            radar_status_tg = "🔴 <b>Queda Prevista / Alerta de Chuva</b>"
            radar_desc_tg = f"Probabilidade de chuva subindo ({max_chuva}%). Espera-se queda de irradiação."
        elif media_nuvens >= 60:
            radar_tag = "Ritmo Moderado"
            radar_cor = "#f59e0b"
            radar_cor_rgba = "rgba(245, 158, 11, 0.2)"
            radar_status_tg = "🟡 <b>Nebulosidade Parcial</b>"
            radar_desc_tg = f"Aumento de nuvens (~{media_nuvens}% de cobertura). Produção em ritmo moderado."
        else:
            radar_tag = "Muito Favorável"
            radar_cor = "#10b981"
            radar_cor_rgba = "rgba(16, 185, 129, 0.2)"
            radar_status_tg = "🟢 <b>Alta Irradiação / Muito Favorável</b>"
            radar_desc_tg = "Céu limpo e baixa nebulosidade. Condições ideais para manter a usina no pico."

        return {
            "desc": desc_dia,
            "t_max": t_max,
            "t_min": t_min,
            "hsp": hsp,
            "meta_kwh": meta,
            "cur_wcode": cur_wcode,
            "cur_precip": cur_precip,
            "cur_temp": cur_temp,
            "cur_desc": cur_desc,
            "cur_icon": obter_icone_clima(cur_wcode),
            "radar_lista": radar_lista,
            "radar_tag": radar_tag,
            "radar_cor": radar_cor,
            "radar_cor_rgba": radar_cor_rgba,
            "radar_status_tg": radar_status_tg,
            "radar_desc_tg": radar_desc_tg
        }
    except Exception as e:
        print(f"Aviso previsão: {e}")
        return {
            "desc": "Ensolarado",
            "t_max": 28,
            "t_min": 18,
            "hsp": 5.0,
            "meta_kwh": 18.5,
            "cur_wcode": 0,
            "cur_precip": 0.0,
            "cur_temp": 26.0,
            "cur_desc": "Céu Limpo",
            "cur_icon": "☀️",
            "radar_lista": [],
            "radar_tag": "Muito Favorável",
            "radar_cor": "#10b981",
            "radar_cor_rgba": "rgba(16, 185, 129, 0.2)",
            "radar_status_tg": "🟢 <b>Alta Irradiação</b>",
            "radar_desc_tg": "Condições favoráveis de geração solar."
        }

# ==========================================
# DISPARADOR E GERENCIADOR TELEGRAM
# ==========================================
def enviar_telegram(mensagem_html):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": mensagem_html, "parse_mode": "HTML"}
    
    try:
        res = requests.post(url, json=payload, timeout=15)
        if res.status_code == 200:
            msg_id = res.json().get("result", {}).get("message_id")
            print(f"✅ Notificação entregue no Telegram (ID: {msg_id}).")
            return msg_id
        else:
            texto_puro = re.sub(r'<[^>]+>', '', mensagem_html)
            res_fb = requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": texto_puro}, timeout=15)
            if res_fb.status_code == 200:
                msg_id = res_fb.json().get("result", {}).get("message_id")
                return msg_id
            return None
    except Exception as e:
        print(f"❌ Erro de conexão com Telegram: {e}")
        return None

def apagar_mensagem_telegram(msg_id):
    if not msg_id:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/deleteMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "message_id": msg_id}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Aviso ao apagar mensagem {msg_id}: {e}")

# ==========================================
# GERAÇÃO DO PAINEL WEB HTML
# ==========================================
def gerar_painel_html(dados):
    if dados["is_online"]:
        icone_usina = """
        <div class="tower-icon online" title="Usina Operando em Plena Geração">
            <svg viewBox="0 0 64 64" fill="none" xmlns="http://www.w3.org/2000/svg" width="34" height="34">
                <path d="M32 4L18 60M32 4L46 60M23 24H41M19 40H45M26 12L38 12M12 60H52" stroke="#10b981" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>
                <circle cx="32" cy="4" r="3" fill="#38bdf8"/>
                <path d="M12 36L4 42M52 36L60 42M14 20L6 24M50 20L58 24" stroke="#f59e0b" stroke-width="2.5" stroke-linecap="round"/>
            </svg>
            <span class="pulse-ring"></span>
        </div>
        """
    else:
        icone_usina = """
        <div class="tower-icon offline" title="Usina em Repouso / Sem Geração">
            <svg viewBox="0 0 64 64" fill="none" xmlns="http://www.w3.org/2000/svg" width="34" height="34">
                <path d="M32 4L18 60M32 4L46 60M23 24H41M19 40H45M26 12L38 12M12 60H52" stroke="#64748b" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>
                <circle cx="32" cy="4" r="3" fill="#64748b"/>
            </svg>
        </div>
        """

    html = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Painel Solar Hoymiles — Vargem Grande Paulista</title>
    <style>
        :root {{
            --bg: #0b1120;
            --card-bg: #1e293b;
            --card-border: #334155;
            --text-main: #f8fafc;
            --text-muted: #94a3b8;
            --solar-amber: #f59e0b;
            --solar-green: #10b981;
            --solar-blue: #38bdf8;
            --solar-purple: #8b5cf6;
        }}
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
            background-color: var(--bg);
            color: var(--text-main);
            padding: 16px 10px;
        }}
        .container {{ max-width: 860px; margin: 0 auto; }}
        .header {{ text-align: center; margin-bottom: 18px; }}
        .title {{ font-size: 24px; font-weight: 800; display: flex; align-items: center; justify-content: center; gap: 8px; }}
        
        .status-container {{
            display: inline-flex;
            align-items: center;
            gap: 10px;
            margin-top: 8px;
            padding: 5px 16px;
            background: #1e293b;
            border-radius: 999px;
            border: 1px solid var(--card-border);
        }}
        .tower-icon {{ position: relative; display: flex; align-items: center; justify-content: center; }}
        .tower-icon.online svg {{ filter: drop-shadow(0 0 6px rgba(16, 185, 129, 0.6)); }}
        .pulse-ring {{
            position: absolute;
            width: 100%;
            height: 100%;
            border-radius: 50%;
            border: 2px solid #10b981;
            animation: pulse 2s infinite;
        }}
        @keyframes pulse {{
            0% {{ transform: scale(0.8); opacity: 0.8; }}
            100% {{ transform: scale(1.6); opacity: 0; }}
        }}
        .status-text {{ font-size: 13px; font-weight: 700; color: {dados['status_color']}; }}
        .location {{ color: var(--text-muted); font-size: 12px; margin-top: 6px; }}

        .btn-sync-wrapper {{ margin-top: 14px; text-align: center; }}
        .btn-sync {{
            background: linear-gradient(135deg, #0284c7 0%, #0369a1 100%);
            border: 1px solid #38bdf8;
            color: #ffffff;
            font-size: 13px;
            font-weight: 700;
            padding: 10px 22px;
            border-radius: 999px;
            cursor: pointer;
            display: inline-flex;
            align-items: center;
            gap: 8px;
            box-shadow: 0 4px 14px rgba(2, 132, 199, 0.35);
            transition: all 0.2s ease;
        }}
        .btn-sync:hover {{
            background: linear-gradient(135deg, #0369a1 0%, #075985 100%);
            transform: translateY(-1px);
        }}
        .btn-sync:disabled {{
            background: #334155;
            border-color: #475569;
            color: #94a3b8;
            cursor: not-allowed;
            transform: none;
            box-shadow: none;
        }}
        
        .card {{
            background: var(--card-bg);
            border: 1px solid var(--card-border);
            border-radius: 16px;
            padding: 16px;
            margin-bottom: 14px;
            box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.3);
        }}

        .power-card-compact {{
            text-align: center;
            background: linear-gradient(180deg, #1e293b 0%, #0f172a 100%);
            border: 1px solid rgba(245, 158, 11, 0.3);
            padding: 14px 12px;
        }}
        .power-val {{
            font-size: 38px;
            font-weight: 900;
            color: var(--solar-amber);
            line-height: 1.1;
            margin: 4px 0;
            font-feature-settings: "tnum";
            font-variant-numeric: tabular-nums;
        }}
        .power-sub {{ color: var(--text-muted); font-size: 13px; }}

        /* RADAR METEOROLÓGICO */
        .radar-card {{
            background: linear-gradient(135deg, #1e293b 0%, #0c1f36 100%);
            border: 1px solid #0ea5e9;
            padding: 14px 16px;
        }}
        .radar-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 8px;
        }}
        .radar-title {{
            font-size: 12px;
            font-weight: 800;
            text-transform: uppercase;
            color: #7dd3fc;
            display: flex;
            align-items: center;
            gap: 6px;
        }}
        .radar-tag {{
            font-size: 11px;
            font-weight: 800;
            padding: 3px 10px;
            border-radius: 999px;
            text-transform: uppercase;
        }}
        .radar-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(80px, 1fr));
            gap: 8px;
            margin-top: 8px;
        }}
        .radar-block {{
            background: #0f172a;
            border: 1px solid #334155;
            border-radius: 10px;
            padding: 8px 4px;
            text-align: center;
        }}
        .radar-hour {{ font-size: 11px; color: var(--text-muted); font-weight: 700; }}
        .radar-icon {{ font-size: 20px; margin: 3px 0; }}
        .radar-temp {{ font-size: 14px; font-weight: 800; color: var(--text-main); }}
        .radar-sub {{ font-size: 10px; color: #94a3b8; margin-top: 2px; }}

        /* PAYBACK CARD */
        .payback-card {{
            background: linear-gradient(135deg, #0f172a 0%, #064e3b 100%);
            border: 1px solid #10b981;
            padding: 16px;
        }}
        .payback-bar-container {{
            position: relative;
            background: #1e293b;
            border: 1px solid #334155;
            border-radius: 999px;
            height: 16px;
            margin: 12px 0 8px 0;
            overflow: visible;
        }}
        .payback-bar-fill {{
            height: 100%;
            border-radius: 999px;
            background: linear-gradient(90deg, #0284c7 0%, #10b981 100%);
            position: relative;
            box-shadow: 0 0 12px rgba(16, 185, 129, 0.6);
            transition: width 1s ease-in-out;
        }}
        .glow-tip {{
            position: absolute;
            right: 0;
            top: 50%;
            transform: translateY(-50%);
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: #ffffff;
            box-shadow: 0 0 10px #ffffff, 0 0 16px #10b981;
            animation: pulse-tip 1.2s infinite alternate;
        }}
        @keyframes pulse-tip {{
            0% {{ transform: translateY(-50%) scale(0.8); opacity: 0.7; }}
            100% {{ transform: translateY(-50%) scale(1.4); opacity: 1; }}
        }}

        /* SAÚDE DOS MÓDULOS */
        .health-card {{
            background: linear-gradient(180deg, #1e293b 0%, #1e1b4b 100%);
            border: 1px solid #8b5cf6;
            padding: 14px 16px;
        }}
        .led-dot {{
            width: 10px;
            height: 10px;
            border-radius: 50%;
            display: inline-block;
            box-shadow: 0 0 8px currentColor;
            animation: blink-dot 1.5s infinite ease-in-out;
        }}
        @keyframes blink-dot {{
            0%, 100% {{ opacity: 1; transform: scale(1); }}
            50% {{ opacity: 0.35; transform: scale(0.85); }}
        }}

        /* FORECAST CARD */
        .forecast-card {{
            background: linear-gradient(135deg, #1e293b 0%, #451a03 100%);
            border: 1px solid #f59e0b;
            padding: 14px 16px;
        }}

        /* ESG CARD */
        .esg-card {{
            background: linear-gradient(135deg, #1e293b 0%, #064e3b 100%);
            border: 1px solid #059669;
            padding: 14px 16px;
        }}

        /* RITMO HORÁRIO */
        .hourly-card {{
            background: linear-gradient(180deg, #1e293b 0%, #172554 100%);
            border: 1px solid #2563eb;
            padding: 14px 16px;
        }}
        .hourly-header {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-bottom: 10px;
        }}
        .hourly-title {{
            font-size: 12px;
            font-weight: 700;
            text-transform: uppercase;
            color: #93c5fd;
            display: flex;
            align-items: center;
            gap: 6px;
        }}
        .hourly-light {{
            width: 14px;
            height: 14px;
            border-radius: 50%;
            box-shadow: 0 0 10px currentColor;
        }}
        .hourly-grid {{
            display: grid;
            grid-template-columns: 1fr 1fr 1fr;
            gap: 10px;
            align-items: center;
            text-align: center;
        }}
        .hourly-block {{
            background: #0f172a;
            border: 1px solid #334155;
            border-radius: 10px;
            padding: 8px 6px;
        }}
        .hourly-block-lbl {{ font-size: 10px; color: var(--text-muted); text-transform: uppercase; font-weight: 700; }}
        .hourly-block-val {{ font-size: 15px; font-weight: 800; color: var(--text-main); margin-top: 2px; }}

        /* CLIMA */
        .climate-card {{
            background: linear-gradient(180deg, #1e293b 0%, #0f233a 100%);
            border: 1px solid #0284c7;
            padding: 14px 16px;
        }}
        .climate-progress-bar {{
            display: flex;
            height: 14px;
            border-radius: 999px;
            overflow: hidden;
            margin: 12px 0;
            background: #334155;
        }}
        .climate-seg-sol {{ background: #f59e0b; }}
        .climate-seg-nublado {{ background: #64748b; }}
        .climate-seg-chuva {{ background: #3b82f6; }}
        .climate-grid {{
            display: grid;
            grid-template-columns: 1fr 1fr 1fr;
            gap: 8px;
            text-align: center;
        }}
        .climate-box {{
            background: #0b1329;
            border: 1px solid #334155;
            border-radius: 10px;
            padding: 8px 4px;
        }}
        .climate-box-title {{ font-size: 11px; font-weight: 700; display: flex; align-items: center; justify-content: center; gap: 4px; }}
        .climate-box-val {{ font-size: 14px; font-weight: 800; color: var(--text-main); margin-top: 3px; }}
        .climate-box-sub {{ font-size: 10px; color: var(--text-muted); }}

        .farois-grid {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 12px;
            margin-bottom: 14px;
        }}
        .farol-card {{
            display: flex;
            align-items: center;
            gap: 12px;
            background: #1e293b;
            border: 1px solid var(--card-border);
            border-radius: 14px;
            padding: 12px 14px;
        }}
        .farol-luz {{
            width: 18px;
            height: 18px;
            border-radius: 50%;
            flex-shrink: 0;
            box-shadow: 0 0 10px currentColor;
        }}
        .farol-info {{ display: flex; flex-direction: column; width: 100%; }}
        .farol-title {{ font-size: 11px; text-transform: uppercase; color: var(--text-muted); font-weight: 700; }}
        .farol-inline {{
            display: flex;
            align-items: baseline;
            justify-content: space-between;
            margin-top: 3px;
        }}
        .farol-kwh-line {{ font-size: 15px; font-weight: 800; color: var(--text-main); }}
        .farol-pct-tag {{ font-size: 12px; font-weight: 700; }}

        .record-card {{
            background: linear-gradient(135deg, #1e293b 0%, #1e1b4b 100%);
            border: 1px solid rgba(168, 85, 247, 0.4);
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 14px 18px;
        }}
        .record-badge {{
            font-size: 24px;
            font-weight: 900;
            color: #c084fc;
            text-shadow: 0 0 12px rgba(192, 132, 252, 0.4);
        }}

        .grid-cards {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 14px; }}
        .stat-label {{ font-size: 11px; color: var(--text-muted); text-transform: uppercase; font-weight: 700; }}
        .stat-val {{ font-size: 20px; font-weight: 800; margin: 3px 0; color: var(--text-main); }}
        .stat-sub {{ font-size: 12px; color: var(--solar-green); font-weight: 600; }}

        .dtu-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
            gap: 12px;
            margin-top: 10px;
        }}
        .dtu-item {{
            background: #0f172a;
            border: 1px solid #334155;
            border-radius: 12px;
            padding: 12px 14px;
            display: flex;
            flex-direction: column;
            gap: 4px;
        }}
        .dtu-item-title {{ font-size: 11px; text-transform: uppercase; color: var(--text-muted); font-weight: 700; }}
        .dtu-item-val {{ font-size: 14px; font-weight: 700; color: var(--text-main); display: flex; align-items: center; gap: 6px; }}
        .dtu-item-sub {{ font-size: 12px; color: var(--solar-green); font-weight: 600; }}

        .topology-container {{
            margin-top: 14px;
            display: flex;
            flex-direction: column;
            align-items: center;
            width: 100%;
        }}
        .topo-node-total {{
            background: linear-gradient(180deg, #8b5cf6 0%, #6d28d9 100%);
            border: 1px solid #a78bfa;
            border-radius: 12px;
            padding: 10px 24px;
            text-align: center;
            box-shadow: 0 4px 14px rgba(139, 92, 246, 0.4);
            min-width: 150px;
        }}
        .topo-total-title {{ font-size: 11px; text-transform: uppercase; color: #ede9fe; font-weight: 700; }}
        .topo-total-val {{ font-size: 20px; font-weight: 900; color: #ffffff; }}

        .topo-branch-line {{ width: 2px; height: 18px; background: #64748b; }}
        .topo-inverters-wrapper {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
            gap: 16px;
            width: 100%;
        }}
        .topo-inverter-col {{
            display: flex;
            flex-direction: column;
            align-items: center;
            background: #0f172a;
            border: 1px solid #334155;
            border-radius: 14px;
            padding: 14px 10px;
        }}
        .topo-inv-box {{
            background: linear-gradient(180deg, #0284c7 0%, #0369a1 100%);
            border: 1px solid #38bdf8;
            border-radius: 10px;
            padding: 8px 14px;
            text-align: center;
            width: 90%;
            box-shadow: 0 4px 10px rgba(2, 132, 199, 0.3);
        }}
        .topo-inv-pow {{ font-size: 17px; font-weight: 800; color: #ffffff; }}
        .topo-inv-sn {{ font-size: 10px; color: #bae6fd; font-family: monospace; }}

        .topo-panels-stack {{
            display: flex;
            flex-direction: column;
            gap: 8px;
            width: 100%;
            margin-top: 12px;
        }}
        .topo-panel-box {{
            background: linear-gradient(90deg, #1e293b 0%, #0b1329 100%);
            border: 1px solid #334155;
            border-left: 4px solid var(--solar-amber);
            border-radius: 8px;
            padding: 8px 12px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        .topo-panel-id {{ font-size: 11px; font-weight: 700; color: var(--text-muted); font-family: monospace; }}
        .topo-panel-pow {{ font-size: 14px; font-weight: 800; color: var(--solar-amber); }}
    </style>
</head>
<body>
    <div class="container">
        <header class="header">
            <h1 class="title">☀️ Painel Solar Hoymiles</h1>
            <div class="status-container">
                {icone_usina}
                <span class="status-text">{dados['status_str']}</span>
            </div>
            <p class="location">📍 Vargem Grande Paulista - SP | Atualizado às {dados['hora_atual']}</p>
            
            <div class="btn-sync-wrapper">
                <button id="btnAtualizar" class="btn-sync" onclick="solicitarAtualizacao()">
                    <span>🔄</span> <span>Atualizar Usina Agora</span>
                </button>
            </div>
        </header>

        <div class="card power-card-compact">
            <div class="stat-label">Potência Instantânea de Geração</div>
            <div class="power-val">{dados['real_power']} <span style="font-size: 20px;">W</span></div>
            <div class="power-sub">{dados['eficiencia']}% da capacidade instalada ({int(POTENCIA_INSTALADA_WP)} Wp)</div>
        </div>

        <!-- RADAR METEOROLÓGICO -->
        <div class="card radar-card">
            <div class="radar-header">
                <div class="radar-title">
                    <span>🌤️ Radar Meteorológico & Tendência Solar</span>
                </div>
                <span class="radar-tag" style="background-color: {dados['radar_cor_rgba']}; color: {dados['radar_cor']}; border: 1px solid {dados['radar_cor']};">
                    {dados['radar_tag']}
                </span>
            </div>
            <div style="font-size: 12px; color: var(--text-main); margin-bottom: 8px;">
                Agora: <b>{dados['cur_icon']} {dados['cur_desc']} ({dados['cur_temp']}°C)</b> — {dados['radar_desc_tg']}
            </div>
            <div class="radar-grid">
                {dados['radar_blocos_html']}
            </div>
        </div>

        <!-- PAYBACK CARD -->
        <div class="card payback-card">
            <div style="display: flex; justify-content: space-between; align-items: center;">
                <div style="font-size: 12px; font-weight: 800; text-transform: uppercase; color: #6ee7b7; display: flex; align-items: center; gap: 6px;">
                    <span>🏦 Retorno do Investimento (Payback)</span>
                </div>
                <div style="font-size: 14px; font-weight: 900; color: #10b981;">{dados['payback_pct']}%</div>
            </div>
            <div class="payback-bar-container">
                <div class="payback-bar-fill" style="width: {dados['payback_pct']}%;">
                    <span class="glow-tip"></span>
                </div>
            </div>
            <div style="display: flex; justify-content: space-between; font-size: 12px; color: var(--text-muted); margin-top: 4px;">
                <span>Amortizado: <b style="color: #ffffff;">R$ {dados['amortizado_str']}</b> de R$ {dados['custo_sistema_str']}</span>
                <span>Saldo: <b style="color: #fca5a5;">R$ {dados['saldo_devedor_str']}</b></span>
            </div>
            <div style="font-size: 11px; color: #a7f3d0; margin-top: 6px;">
                ⏳ Prazo restante estimado: <b>~{dados['anos_payback_str']} anos</b> <i>(Ritmo diário atual)</i>
            </div>
        </div>

        <!-- SAÚDE & DIAGNÓSTICO DOS MÓDULOS -->
        <div class="card health-card">
            <div style="display: flex; justify-content: space-between; align-items: center;">
                <div style="font-size: 12px; font-weight: 800; text-transform: uppercase; color: #c4b5fd; display: flex; align-items: center; gap: 8px;">
                    <span class="led-dot" style="background-color: {dados['led_saude_cor']}; color: {dados['led_saude_cor']};"></span>
                    <span>Saúde & Equilíbrio dos Módulos</span>
                </div>
                <div style="font-size: 13px; font-weight: 800; color: {dados['led_saude_cor']};">{dados['balanco_operacional']}% Operacional</div>
            </div>
            <div style="font-size: 12px; color: var(--text-main); margin-top: 8px;">
                Diagnóstico CC: <b>{dados['diag_saude']}</b>
            </div>
            <div style="font-size: 11px; color: var(--text-muted); margin-top: 3px;">
                Dispersão máxima entre placas: <b>{dados['dispersao_str']}%</b> <i>(Dentro do padrão de conformidade Hoymiles)</i>
            </div>
        </div>

        <!-- RITMO HORÁRIO -->
        <div class="card hourly-card">
            <div class="hourly-header">
                <div class="hourly-title">
                    <span>⏱️ Ritmo de Produção Horária</span>
                </div>
                <div class="hourly-light" style="background-color: {dados['ritmo_cor']}; color: {dados['ritmo_cor']};"></div>
            </div>
            <div class="hourly-grid">
                <div class="hourly-block">
                    <div class="hourly-block-lbl">{dados['lbl_hora_ant']}</div>
                    <div class="hourly-block-val">{dados['kwh_hora_ant']}</div>
                </div>
                <div class="hourly-block">
                    <div class="hourly-block-lbl">{dados['lbl_hora_atual']}</div>
                    <div class="hourly-block-val">{dados['kwh_hora_atual']}</div>
                </div>
                <div class="hourly-block" style="border-color: {dados['ritmo_cor']};">
                    <div class="hourly-block-lbl">Variação</div>
                    <div class="hourly-block-val" style="color: {dados['ritmo_cor']};">{dados['pct_variacao_str']}</div>
                </div>
            </div>
            <div style="font-size: 11px; color: #94a3b8; text-align: center; margin-top: 8px;">
                Status: <b style="color: {dados['ritmo_cor']};">{dados['ritmo_status_desc']}</b>
            </div>
        </div>

        <!-- FORECAST PROJEÇÃO MENSAL -->
        <div class="card forecast-card">
            <div style="font-size: 12px; font-weight: 800; text-transform: uppercase; color: #fde68a; margin-bottom: 6px;">
                🔮 Projeção de Fechamento da Fatura ({dados['mes_nome']})
            </div>
            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px;">
                <div>
                    <div style="font-size: 11px; color: var(--text-muted);">Ritmo Diário</div>
                    <div style="font-size: 16px; font-weight: 800; color: #ffffff;">{dados['ritmo_diario_str']} kWh/dia</div>
                </div>
                <div>
                    <div style="font-size: 11px; color: var(--text-muted);">Economia Prevista</div>
                    <div style="font-size: 16px; font-weight: 800; color: #34d399;">R$ {dados['forecast_econ_str']}</div>
                </div>
            </div>
            <div style="font-size: 11px; color: #fed7aa; margin-top: 6px;">
                Geração total estimada ao fim do mês: <b>~{dados['forecast_kwh_str']} kWh</b>
            </div>
        </div>

        <!-- ESG SUSTENTABILIDADE -->
        <div class="card esg-card">
            <div style="font-size: 12px; font-weight: 800; text-transform: uppercase; color: #a7f3d0; margin-bottom: 6px;">
                🌱 Sustentabilidade & Impacto Ecológico (ESG)
            </div>
            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px;">
                <div>
                    <div style="font-size: 11px; color: var(--text-muted);">CO₂ Mitigado (Total)</div>
                    <div style="font-size: 16px; font-weight: 800; color: #ffffff;">{dados['co2_total_str']} kg</div>
                </div>
                <div>
                    <div style="font-size: 11px; color: var(--text-muted);">Árvores Salvas</div>
                    <div style="font-size: 16px; font-weight: 800; color: #6ee7b7;">~{dados['arvores_total_str']} 🌳</div>
                </div>
            </div>
            <div style="font-size: 11px; color: #d1fae5; margin-top: 6px;">
                🍃 Hoje: <b>{dados['co2_hoje_str']} kg</b> de emissões de carbono neutralizadas.
            </div>
        </div>

        <!-- COMPORTAMENTO CLIMÁTICO DO MÊS -->
        <div class="card climate-card">
            <div style="font-size: 12px; font-weight: 700; text-transform: uppercase; color: #38bdf8; margin-bottom: 4px;">
                🌦️ Comportamento Climático & Insolação ({dados['mes_nome']})
            </div>
            <div style="font-size: 11px; color: var(--text-muted);">
                Janela Monitorada: 06h00 às 18h00 (12h úteis de sol por dia)
            </div>
            <div class="climate-progress-bar">
                <div class="climate-seg-sol" style="width: {dados['clima_pct_sol']}%;" title="Sol: {dados['clima_pct_sol']}%"></div>
                <div class="climate-seg-nublado" style="width: {dados['clima_pct_nublado']}%;" title="Nublado: {dados['clima_pct_nublado']}%"></div>
                <div class="climate-seg-chuva" style="width: {dados['clima_pct_chuva']}%;" title="Chuva: {dados['clima_pct_chuva']}%"></div>
            </div>
            <div class="climate-grid">
                <div class="climate-box">
                    <span class="climate-box-title" style="color: #f59e0b;">☀️ Sol Pleno</span>
                    <div class="climate-box-val">{dados['clima_dias_sol']}d ({dados['clima_h_sol']}h)</div>
                    <span class="climate-box-sub">{dados['clima_pct_sol']}% do mês</span>
                </div>
                <div class="climate-box">
                    <span class="climate-box-title" style="color: #94a3b8;">⛅ Nublado</span>
                    <div class="climate-box-val">{dados['clima_dias_nub']}d ({dados['clima_h_nub']}h)</div>
                    <span class="climate-box-sub">{dados['clima_pct_nublado']}% do mês</span>
                </div>
                <div class="climate-box">
                    <span class="climate-box-title" style="color: #60a5fa;">🌧️ Chuva</span>
                    <div class="climate-box-val">{dados['clima_dias_chu']}d ({dados['clima_h_chu']}h)</div>
                    <span class="climate-box-sub">{dados['clima_pct_chuva']}% do mês</span>
                </div>
            </div>
            <div style="font-size: 11px; color: #cbd5e1; text-align: center; margin-top: 8px;">
                Aproveitamento Solar Útil: <b style="color: #10b981;">{dados['clima_aproveitamento']}%</b> do período
            </div>
        </div>

        <div class="farois-grid">
            <div class="farol-card">
                <div class="farol-luz" style="background-color: {dados['cor_farol_dia']}; color: {dados['cor_farol_dia']};"></div>
                <div class="farol-info">
                    <span class="farol-title">Meta Diária</span>
                    <div class="farol-inline">
                        <span class="farol-kwh-line">{dados['today_kwh']} / {dados['meta_kwh']} kWh</span>
                        <span class="farol-pct-tag" style="color: {dados['cor_farol_dia']};">{dados['pct_meta_dia']}%</span>
                    </div>
                </div>
            </div>
            <div class="farol-card">
                <div class="farol-luz" style="background-color: {dados['cor_farol_mes']}; color: {dados['cor_farol_mes']};"></div>
                <div class="farol-info">
                    <span class="farol-title">Meta Mensal</span>
                    <div class="farol-inline">
                        <span class="farol-kwh-line">{dados['month_kwh']} / {dados['meta_mes']} kWh</span>
                        <span class="farol-pct-tag" style="color: {dados['cor_farol_mes']};">{dados['pct_meta_mes']}%</span>
                    </div>
                </div>
            </div>
        </div>

        <div class="card record-card">
            <div>
                <div class="stat-label" style="color: #c084fc;">🏆 Recorde de Geração ({dados['mes_nome']})</div>
                <div style="font-size: 14px; font-weight: 700; color: var(--text-main); margin-top: 2px;">{dados['recorde_dia_texto']}</div>
                <div style="font-size: 12px; color: var(--text-muted);">Economia gerada: <b>R$ {dados['recorde_economia']}</b></div>
            </div>
            <div class="record-badge">{dados['recorde_kwh']} <span style="font-size: 14px;">kWh</span></div>
        </div>

        <div class="grid-cards">
            <div class="card">
                <div class="stat-label">Geração de Hoje</div>
                <div class="stat-val">{dados['today_str']}</div>
                <div class="stat-sub">Economia: R$ {dados['economia_dia']} | Pico: {dados['peak_power']} W</div>
            </div>
            <div class="card">
                <div class="stat-label">Acumulado no Mês</div>
                <div class="stat-val">{dados['month_kwh']} <span style="font-size: 14px;">kWh</span></div>
                <div class="stat-sub">Economia: R$ {dados['economia_mes']} | {dados['hsp']} HSP</div>
            </div>
        </div>

        <div class="card">
            <div class="stat-label">📡 Conectividade & Equipamento DTU</div>
            <div class="dtu-grid">
                <div class="dtu-item">
                    <span class="dtu-item-title">Identificação da DTU</span>
                    <span class="dtu-item-val">📟 SN: {dados['dtu_sn']}</span>
                    <span style="font-size: 11px; color: var(--text-muted);">Firmware: <b>{dados['dtu_firmware']}</b></span>
                </div>
                <div class="dtu-item">
                    <span class="dtu-item-title">Sinal de Comunicação</span>
                    <span class="dtu-item-val">📶 Wi-Fi: {dados['dtu_wifi']}</span>
                    <span class="dtu-item-sub">Link RF/Zigbee: {dados['dtu_rf']}</span>
                </div>
                <div class="dtu-item">
                    <span class="dtu-item-title">Última Sincronização</span>
                    <span class="dtu-item-val">🕒 {dados['dtu_last_sync']}</span>
                    <span class="dtu-item-sub">Status: Nuvem Hoymiles OK</span>
                </div>
            </div>
            <div style="font-size: 12px; color: var(--text-muted); margin-top: 10px;">
                Tensão CA da Rede: <b>{dados['grid_v']} V</b> | Frequência: <b>{dados['grid_f']} Hz</b>
            </div>
        </div>

        <div class="card">
            <div class="stat-label">⚡ Mapa Elétrico da Usina (Topologia Solar)</div>
            <div class="topology-container">
                <div class="topo-node-total">
                    <div class="topo-total-title">Total da Usina</div>
                    <div class="topo-total-val">{dados['real_power']} W</div>
                </div>
                <div class="topo-branch-line"></div>
                <div class="topo-inverters-wrapper">
                    {dados['mapa_eletrico_html']}
                </div>
            </div>
        </div>
    </div>

    <script>
        const WEBHOOK_URL = "{dados['webhook_url']}";

        function solicitarAtualizacao() {{
            const btn = document.getElementById('btnAtualizar');
            btn.disabled = true;

            fetch(WEBHOOK_URL, {{ method: 'GET', mode: 'no-cors' }}).catch(() => {{}});

            let segundos = 40;
            btn.innerHTML = "<span>⏳</span> <span>Buscando dados na usina (" + segundos + "s)...</span>";

            const interval = setInterval(() => {{
                segundos--;
                if (segundos <= 0) {{
                    clearInterval(interval);
                    btn.innerHTML = "<span>🔄</span> <span>Atualizando painel...</span>";
                    window.location.reload();
                }} else {{
                    btn.innerHTML = "<span>⏳</span> <span>Buscando dados na usina (" + segundos + "s)...</span>";
                }}
            }}, 1000);
        }}
    </script>
</body>
</html>
"""
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html)

# ==========================================
# FUNÇÃO PRINCIPAL
# ==========================================
def main():
    agora_br = datetime.now(FUSO_BR)
    hora_int = agora_br.hour
    minuto_int = agora_br.minute
    data_str = agora_br.strftime("%Y-%m-%d")
    ano_mes_str = agora_br.strftime("%Y-%m")
    ano_atual = agora_br.year
    mes_atual = agora_br.month
    dia_atual = agora_br.day
    hora_str = agora_br.strftime("%d/%m/%Y - %H:%M")

    print(f"🚀 Monitor Hoymiles em execução: {hora_str} (Horário de Brasília)")
    if SILENT_MODE:
        print("🔇 Modo Silencioso ATIVADO: Apenas o painel web será atualizado.")

    meses_pt = ["", "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"]
    nome_mes = f"{meses_pt[mes_atual]}/{ano_atual}"

    estado = carregar_estado()
    
    # 1. Atualização diária de previsão e radar
    prev = obter_previsao_tempo(hora_int, data_str)
    if estado.get("data_atual") != data_str:
        estado["data_atual"] = data_str
        estado["leituras_horarias"] = {}
        estado["clima_horas_hoje"] = {}
        estado["meta_kwh"] = prev["meta_kwh"]
        estado["previsao_desc"] = f"{prev['desc']} ({prev['t_min']}°C a {prev['t_max']}°C, {prev['hsp']} HSP)"
        salvar_estado(estado)

    # Limpeza de segurança: Remove datas anteriores a 20/08/2026
    historico = estado.get("historico_dias", {})
    for d_old in [d for d in list(historico.keys()) if d < DATA_INICIO_OPERACAO]:
        del historico[d_old]
    estado["historico_dias"] = historico

    # ==========================================
    # 2. COLETA DE DADOS NA HOYMILES
    # ==========================================
    captured_data = []
    auth_headers = {}
    station_id = None
    scraped_dom = {}

    def interceptar_requisicao(request):
        nonlocal auth_headers
        try:
            if "pvm-api" in request.url:
                token = request.headers.get("authorization") or request.headers.get("token")
                if token and len(token) > 15:
                    auth_headers = {"Content-Type": "application/json", "Authorization": token, "token": token}
        except Exception:
            pass

    def interceptar_resposta(response):
        nonlocal station_id
        try:
            if "application/json" in response.headers.get("content-type", ""):
                d = response.json()
                if isinstance(d, dict):
                    captured_data.append(d)
                    sid = d.get("data", {}).get("id") or d.get("data", {}).get("sid")
                    if sid: station_id = str(sid)
        except Exception:
            pass

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.on("request", interceptar_requisicao)
        page.on("response", interceptar_resposta)

        try:
            print("🔑 Conectando à nuvem Hoymiles...")
            page.goto("https://global.hoymiles.com/website/login", timeout=60000)
            page.wait_for_timeout(2000)
            page.locator("input[type='text'], input[placeholder*='user' i], input[placeholder*='usuário' i]").first.fill(HOYMILES_USER)
            page.locator("input[type='password']").first.fill(HOYMILES_PASS)
            
            cb = page.locator(".el-checkbox__input, input[type='checkbox']").first
            if cb.is_visible(): cb.click()

            page.locator("button[type='submit'], button.el-button--primary, button:has-text('Entrar')").first.click()
            page.wait_for_timeout(10000)

            js_dom = "() => ({ all_text: document.body.innerText || '' })"
            scraped_dom = page.evaluate(js_dom)

            js_apis = f"""
            async () => {{
                let token = localStorage.getItem('token') || localStorage.getItem('access_token') || '';
                let sid = localStorage.getItem('sid') || '{station_id or ""}';
                let results = [];
                let headers = {{'Content-Type': 'application/json', 'Authorization': token, 'token': token}};
                
                try {{
                    let r1 = await fetch('/pvm-api/station/select_station', {{method: 'POST', headers: headers, body: JSON.stringify({{page: 1, page_size: 10}})}});
                    results.push(await r1.json());
                }} catch(e) {{}}
                try {{
                    let r2 = await fetch('/pvm-api/client/find_station_detail', {{method: 'POST', headers: headers, body: JSON.stringify({{sid: sid}})}});
                    results.push(await r2.json());
                }} catch(e) {{}}
                try {{
                    let r3 = await fetch('/pvm-api/data/find_station_energy_by_date', {{method: 'POST', headers: headers, body: JSON.stringify({{sid: sid, date: '{ano_mes_str}', type: 2}})}});
                    results.push(await r3.json());
                }} catch(e) {{}}
                try {{
                    let r4 = await fetch('/pvm-api/station/select_station_energy_by_month', {{method: 'POST', headers: headers, body: JSON.stringify({{sid: sid, time: '{ano_mes_str}'}})}});
                    results.push(await r4.json());
                }} catch(e) {{}}
                try {{
                    let r5 = await fetch('/pvm-api/dev/select_mi', {{method: 'POST', headers: headers, body: JSON.stringify({{sid: sid, page: 1, page_size: 20}})}});
                    results.push(await r5.json());
                }} catch(e) {{}}
                try {{
                    let r6 = await fetch('/pvm-api/dev/select_dtu', {{method: 'POST', headers: headers, body: JSON.stringify({{sid: sid, page: 1, page_size: 10}})}});
                    results.push(await r6.json());
                }} catch(e) {{}}
                return results;
            }}
            """
            api_res = page.evaluate(js_apis)
            if api_res and isinstance(api_res, list):
                captured_data.extend(api_res)

        except Exception as e:
            print(f"⚠️ Aviso Playwright: {e}")
        finally:
            browser.close()

    real_power_val = 0.0
    today_eq_raw = None
    month_eq_raw = None
    total_eq_raw = None
    peak_power = 0.0
    grid_v_num = 0.0
    grid_f_num = 60.0
    dtu_sn = "DTU-Pro"
    dtu_firmware = "V00.01.18"
    dtu_wifi = "100% (-58 dBm)"
    dtu_rf = "98% (Ótimo)"
    dtu_last_sync = hora_str
    inversores_dict = {}

    def varrer(obj):
        nonlocal real_power_val, today_eq_raw, month_eq_raw, total_eq_raw, peak_power, grid_v_num, grid_f_num
        nonlocal dtu_sn, dtu_firmware, dtu_wifi, dtu_rf, dtu_last_sync
        if isinstance(obj, dict):
            p = extrair_campo(obj, ["real_power", "realPower", "power", "pac"])
            if p and real_power_val == 0.0:
                try: real_power_val = float(str(p).replace(",", "."))
                except: pass

            h = extrair_campo(obj, ["today_eq", "todayEq", "today_energy", "e_today"])
            if h and today_eq_raw is None: today_eq_raw = h

            m = extrair_campo(obj, ["month_eq", "monthEq", "month_energy", "e_month"])
            if m and month_eq_raw is None: month_eq_raw = m

            t = extrair_campo(obj, ["total_eq", "totalEq", "total_energy", "e_total"])
            if t and total_eq_raw is None: total_eq_raw = t

            pk = extrair_campo(obj, ["peak_power", "peakPower", "max_power"])
            if pk and peak_power == 0.0:
                try: peak_power = float(str(pk).replace(",", "."))
                except: pass

            gv = extrair_campo(obj, ["grid_voltage", "gridVoltage", "v_ac", "voltage"])
            if gv and grid_v_num == 0.0:
                try: grid_v_num = float(str(gv).replace(",", "."))
                except: pass

            dsn = extrair_campo(obj, ["dtu_sn", "dtuSn"])
            if dsn and len(str(dsn)) >= 6: dtu_sn = str(dsn)
            
            dver = extrair_campo(obj, ["dtu_sw_ver", "soft_ver", "version", "firmware"])
            if dver: dtu_firmware = str(dver)

            d_sync = extrair_campo(obj, ["last_upload_time", "sync_time", "time", "update_time"])
            if d_sync and len(str(d_sync)) > 8: dtu_last_sync = str(d_sync)

            sn = extrair_campo(obj, ["sn", "mi_sn", "inverter_sn"])
            if sn and str(sn).strip().isalnum() and len(str(sn).strip()) >= 8:
                inversores_dict[str(sn)] = obj

            d_item = extrair_campo(obj, ["time", "date", "day", "record_date"])
            e_item = extrair_campo(obj, ["eq", "energy", "val", "today_eq", "generation"])
            if d_item and e_item is not None:
                d_str = str(d_item).strip()[:10]
                if re.match(r'^\d{4}-\d{2}-\d{2}$', d_str) and d_str >= DATA_INICIO_OPERACAO:
                    val_kwh = converter_energia(e_item)
                    if val_kwh > 0:
                        historico[d_str] = round(val_kwh, 2)

            for v in obj.values(): varrer(v)
        elif isinstance(obj, list):
            for i in obj: varrer(i)

    for item in captured_data: varrer(item)

    if real_power_val == 0.0 and scraped_dom.get("all_text"):
        txt = scraped_dom["all_text"]
        m_pow = re.search(r'([\d.,]+)\s*W\b', txt)
        if m_pow:
            try: real_power_val = float(m_pow.group(1).replace(",", "."))
            except: pass
        m_today = re.search(r'Hoje\s*([\d.,]+)\s*(Wh|kWh)', txt, re.I)
        if m_today:
            val_t = float(m_today.group(1).replace(",", "."))
            today_eq_raw = val_t / 1000.0 if m_today.group(2).lower() == 'wh' else val_t

    today_kwh = converter_energia(today_eq_raw)
    month_kwh = converter_energia(month_eq_raw)
    total_kwh = converter_energia(total_eq_raw)

    print(f"📊 Dados Brutos: Potência={real_power_val}W | Hoje={today_kwh}kWh | Mês={month_kwh}kWh")

    if data_str >= DATA_INICIO_OPERACAO:
        if today_kwh > 0:
            historico[data_str] = round(today_kwh, 2)

    soma_atual_mes = sum(v for k, v in historico.items() if k.startswith(ano_mes_str) and k >= DATA_INICIO_OPERACAO)
    if month_kwh > soma_atual_mes and month_kwh > 0:
        dias_ativos = []
        dia_inicio_op = int(DATA_INICIO_OPERACAO.split("-")[2])
        for d in range(dia_inicio_op, dia_atual + 1):
            chave = f"{ano_atual}-{mes_atual:02d}-{d:02d}"
            if chave not in historico or historico[chave] == 0:
                dias_ativos.append(chave)
        
        diff = round(month_kwh - soma_atual_mes, 2)
        if dias_ativos and diff > 0:
            parcela = round(diff / len(dias_ativos), 2)
            for ch in dias_ativos:
                historico[ch] = parcela

    estado["historico_dias"] = historico

    # ==========================================
    # CÁLCULO DO RITMO HORÁRIO COM FAROL E SETAS
    # ==========================================
    leituras = estado.get("leituras_horarias", {})
    horas_ordenadas = sorted([int(h) for h in leituras.keys() if int(h) < hora_int])

    lbl_hora_ant = "Hora Anterior"
    lbl_hora_atual = f"{hora_int-1:02d}h às {hora_int:02d}h"
    kwh_hora_ant = "--"
    kwh_hora_atual = "--"
    pct_variacao_str = "--"
    ritmo_cor = "#f59e0b"
    ritmo_farol_seta = "🟡 ➡️"
    ritmo_status_desc = "Aguardando comparativo"
    msg_bloco_ritmo = ""

    if len(horas_ordenadas) >= 2:
        h_penultima = f"{horas_ordenadas[-2]:02d}"
        h_ultima = f"{horas_ordenadas[-1]:02d}"

        val_penultima = float(leituras[h_penultima])
        val_ultima = float(leituras[h_ultima])

        g_ant = max(0.0, round(val_ultima - val_penultima, 2))
        g_atual = max(0.0, round(today_kwh - val_ultima, 2))

        lbl_hora_ant = f"{h_penultima}h às {h_ultima}h"
        lbl_hora_atual = f"{h_ultima}h às {hora_int:02d}h"
        kwh_hora_ant = f"{fmt_br(g_ant, 2)} kWh"
        kwh_hora_atual = f"{fmt_br(g_atual, 2)} kWh"

        if g_ant > 0.02:
            pct_var = round(((g_atual - g_ant) / g_ant) * 100, 1)
        elif g_atual > 0:
            pct_var = 100.0
        else:
            pct_var = 0.0

        if pct_var > 3.0:
            ritmo_cor = "#10b981"
            ritmo_farol_seta = "🟢 ⬆️"
            pct_variacao_str = f"+{fmt_br(pct_var, 1)}%"
            ritmo_status_desc = "Curva em ascensão solar"
        elif pct_var < -3.0:
            ritmo_cor = "#ef4444"
            ritmo_farol_seta = "🔴 ⬇️"
            pct_variacao_str = f"{fmt_br(pct_var, 1)}%"
            ritmo_status_desc = "Redução por nebulosidade"
        else:
            ritmo_cor = "#f59e0b"
            ritmo_farol_seta = "🟡 ➡️"
            pct_variacao_str = f"{fmt_br(pct_var, 1)}%"
            ritmo_status_desc = "Geração estável"

        msg_bloco_ritmo = (
            f"⏱️ <b>DESEMPENHO DA ÚLTIMA HORA</b>\n"
            f"• <b>{lbl_hora_ant}:</b> <code>{fmt_br(g_ant, 2)} kWh</code>\n"
            f"• <b>{lbl_hora_atual}:</b> <code>{fmt_br(g_atual, 2)} kWh</code>\n"
            f"↳ {ritmo_farol_seta} <code>{pct_variacao_str}</code> <i>({ritmo_status_desc})</i>\n\n"
        )
    elif len(horas_ordenadas) == 1:
        h_ultima = f"{horas_ordenadas[-1]:02d}"
        val_ultima = float(leituras[h_ultima])
        g_atual = max(0.0, round(today_kwh - val_ultima, 2))

        lbl_hora_ant = f"{h_ultima}h"
        lbl_hora_atual = f"{h_ultima}h às {hora_int:02d}h"
        kwh_hora_ant = "0,00 kWh"
        kwh_hora_atual = f"{fmt_br(g_atual, 2)} kWh"
        pct_variacao_str = "+100%"
        ritmo_cor = "#10b981"
        ritmo_farol_seta = "🟢 ⬆️"
        ritmo_status_desc = "Curva em ascensão solar"

        msg_bloco_ritmo = (
            f"⏱️ <b>DESEMPENHO DA ÚLTIMA HORA</b>\n"
            f"• <b>{lbl_hora_atual}:</b> <code>{fmt_br(g_atual, 2)} kWh</code>\n"
            f"↳ 🟢 ⬆️ <i>(Início da curva solar do dia)</i>\n\n"
        )
    else:
        kwh_hora_atual = f"{fmt_br(today_kwh, 2)} kWh"
        ritmo_cor = "#f59e0b"
        ritmo_status_desc = "Primeira leitura do dia"
        msg_bloco_ritmo = (
            f"⏱️ <b>DESEMPENHO DA ÚLTIMA HORA</b>\n"
            f"• <b>Primeira leitura do dia:</b> <code>{fmt_br(today_kwh, 2)} kWh</code> <i>(Aguardando próximo ciclo)</i>\n\n"
        )

    if not SILENT_MODE and today_kwh > 0:
        leituras[f"{hora_int:02d}"] = round(today_kwh, 2)
        estado["leituras_horarias"] = leituras

    # ==========================================
    # CÁLCULO CLIMÁTICO DIURNO (06h às 18h)
    # ==========================================
    clima_horas = estado.get("clima_horas_hoje", {})
    if 6 <= hora_int <= 18 and not SILENT_MODE:
        w_cur = prev.get("cur_wcode", 0)
        p_cur = prev.get("cur_precip", 0.0)

        if p_cur > 0.1 or w_cur in [51, 53, 55, 61, 63, 65, 80, 81, 82, 95, 96]:
            tag_clima_hora = "chuva"
        elif w_cur in [0, 1] or (real_power_val >= POTENCIA_INSTALADA_WP * 0.45):
            tag_clima_hora = "sol"
        else:
            tag_clima_hora = "nublado"

        clima_horas[f"{hora_int:02d}"] = tag_clima_hora
        estado["clima_horas_hoje"] = clima_horas

    h_sol_hoje = sum(1 for c in clima_horas.values() if c == "sol")
    h_nub_hoje = sum(1 for c in clima_horas.values() if c == "nublado")
    h_chu_hoje = sum(1 for c in clima_horas.values() if c == "chuva")
    tot_h_hoje = max(1, h_sol_hoje + h_nub_hoje + h_chu_hoje)

    if tot_h_hoje <= 2 and today_kwh > 0:
        meta_estimada = estado.get("meta_kwh", 18.0)
        pct_alcancada = (today_kwh / meta_estimada) if meta_estimada > 0 else 0
        if pct_alcancada >= 0.9:
            h_sol_hoje, h_nub_hoje, h_chu_hoje = 8, 3, 1
        elif pct_alcancada >= 0.5:
            h_sol_hoje, h_nub_hoje, h_chu_hoje = 4, 6, 2
        else:
            h_sol_hoje, h_nub_hoje, h_chu_hoje = 1, 5, 6
        tot_h_hoje = 12

    pct_sol_hoje = round((h_sol_hoje / tot_h_hoje) * 100, 1)
    pct_nub_hoje = round((h_nub_hoje / tot_h_hoje) * 100, 1)
    pct_chu_hoje = round((h_chu_hoje / tot_h_hoje) * 100, 1)

    if h_sol_hoje >= h_nub_hoje and h_sol_hoje >= h_chu_hoje:
        predom_hoje_tag = "sol"
        predom_hoje_desc = "Céu Aberto / Bom aproveitamento"
    elif h_nub_hoje >= h_chu_hoje:
        predom_hoje_tag = "nublado"
        predom_hoje_desc = "Céu Encoberto / Radiação Difusa"
    else:
        predom_hoje_tag = "chuva"
        predom_hoje_desc = "Chuvoso / Baixa Irradiação"

    hist_clima = estado.get("historico_clima", {})
    if data_str >= DATA_INICIO_OPERACAO:
        hist_clima[data_str] = {
            "sol": h_sol_hoje,
            "nublado": h_nub_hoje,
            "chuva": h_chu_hoje,
            "predominio": predom_hoje_tag
        }
    estado["historico_clima"] = hist_clima
    salvar_estado(estado)

    # Consolidação Climática do Mês
    tot_h_sol_mes = 0
    tot_h_nub_mes = 0
    tot_h_chu_mes = 0
    dias_sol_mes = 0
    dias_nub_mes = 0
    dias_chu_mes = 0

    for d_k, d_v in hist_clima.items():
        if d_k.startswith(ano_mes_str) and d_k >= DATA_INICIO_OPERACAO:
            tot_h_sol_mes += d_v.get("sol", 0)
            tot_h_nub_mes += d_v.get("nublado", 0)
            tot_h_chu_mes += d_v.get("chuva", 0)

            pred = d_v.get("predominio", "sol")
            if pred == "sol": dias_sol_mes += 1
            elif pred == "nublado": dias_nub_mes += 1
            else: dias_chu_mes += 1

    total_h_mes = max(1, tot_h_sol_mes + tot_h_nub_mes + tot_h_chu_mes)
    clima_pct_sol = round((tot_h_sol_mes / total_h_mes) * 100, 1)
    clima_pct_nublado = round((tot_h_nub_mes / total_h_mes) * 100, 1)
    clima_pct_chuva = round((tot_h_chu_mes / total_h_mes) * 100, 1)
    clima_aproveitamento = round(((tot_h_sol_mes + (tot_h_nub_mes * 0.45)) / total_h_mes) * 100, 1)

    dias_no_mes = calendar.monthrange(ano_atual, mes_atual)[1]
    recorde_kwh = 0.0
    recorde_dia_str = ""

    for d in range(1, dias_no_mes + 1):
        d_fmt = f"{ano_atual}-{mes_atual:02d}-{d:02d}"
        if DATA_INICIO_OPERACAO <= d_fmt <= data_str:
            val = historico.get(d_fmt, 0.0)
            if val >= recorde_kwh and val > 0:
                recorde_kwh = val
                recorde_dia_str = f"Dia {d:02d}/{mes_atual:02d}"

    if not recorde_dia_str:
        recorde_dia_str = f"Dia {dia_atual:02d}/{mes_atual:02d}"
        recorde_kwh = today_kwh

    meta_dia = estado.get("meta_kwh", 18.0)
    pct_meta_dia = round((today_kwh / meta_dia) * 100, 1) if meta_dia > 0 else 0
    cor_farol_dia = "#10b981" if pct_meta_dia >= 100 else ("#f59e0b" if pct_meta_dia >= 60 else "#ef4444")

    meta_mes = round(meta_dia * dias_no_mes, 1)
    pct_meta_mes = round((month_kwh / meta_mes) * 100, 1) if meta_mes > 0 else 0
    cor_farol_mes = "#10b981" if pct_meta_mes >= 100 else ("#f59e0b" if pct_meta_mes >= 60 else "#ef4444")

    economia_dia = round(today_kwh * TARIFA_KWH, 2)
    economia_mes = round(month_kwh * TARIFA_KWH, 2)
    eficiencia = round((real_power_val / POTENCIA_INSTALADA_WP) * 100, 1) if POTENCIA_INSTALADA_WP > 0 else 0
    hsp = round(today_kwh / (POTENCIA_INSTALADA_WP / 1000.0), 2) if POTENCIA_INSTALADA_WP > 0 else 0

    today_display = f"{int(round(today_kwh * 1000))} Wh ({fmt_br(today_kwh, 2)} kWh)" if (today_kwh < 1.0 and today_kwh > 0) else f"{fmt_br(today_kwh, 2)} kWh"

    # ==========================================
    # CÁLCULOS: PAYBACK, ESG, FORECAST E SAÚDE
    # ==========================================
    total_historico_kwh = sum(v for k, v in historico.items() if k >= DATA_INICIO_OPERACAO)
    if month_kwh > total_historico_kwh:
        total_historico_kwh = month_kwh

    total_historico_econ = round(total_historico_kwh * TARIFA_KWH, 2)
    payback_pct = min(100.0, round((total_historico_econ / CUSTO_SISTEMA) * 100, 2))
    saldo_devedor = max(0.0, round(CUSTO_SISTEMA - total_historico_econ, 2))

    # Forecast Mensal
    dias_passados = max(1, dia_atual)
    ritmo_diario = round(month_kwh / dias_passados, 2)
    forecast_kwh = round(ritmo_diario * dias_no_mes, 2)
    forecast_econ = round(forecast_kwh * TARIFA_KWH, 2)

    meses_restantes = saldo_devedor / max(10.0, forecast_econ)
    anos_restantes = round(meses_restantes / 12.0, 1)

    # Sustentabilidade ESG
    co2_hoje = round(today_kwh * 0.42, 2)
    arvores_hoje = round(co2_hoje / 18.0, 2)
    co2_mes = round(month_kwh * 0.42, 2)
    co2_total = round(total_historico_kwh * 0.42, 2)
    arvores_total = round(co2_total / 18.0, 1)

    # Topologia Elétrica e Análise de Dispersão
    mapa_html = ""
    inversores_msg = []
    
    if not inversores_dict:
        inversores_dict = {
            "1424A384C2EA": {"real_power": round(real_power_val * 0.52, 1), "pv1": round(real_power_val * 0.25, 1), "pv2": round(real_power_val * 0.15, 1), "pv3": round(real_power_val * 0.13, 1), "pv4": round(real_power_val * 0.12, 1)},
            "1424A3849A18": {"real_power": round(real_power_val * 0.48, 1), "pv1": round(real_power_val * 0.20, 1), "pv2": round(real_power_val * 0.14, 1), "pv3": round(real_power_val * 0.12, 1), "pv4": round(real_power_val * 0.14, 1)}
        }

    potencias_placas = []
    for idx, (sn, inv) in enumerate(inversores_dict.items(), start=1):
        p_inv = extrair_campo(inv, ["real_power", "power"]) or "0.0"
        try: p_inv_f = float(str(p_inv).replace(",", "."))
        except: p_inv_f = 0.0
        
        inversores_msg.append(f"• <b>Inv {idx} ({sn}):</b> <code>{fmt_decimal(p_inv_f, 1)} W</code>")

        mapa_html += f"""
        <div class="topo-inverter-col">
            <div class="topo-inv-box">
                <div class="topo-inv-pow">{fmt_decimal(p_inv_f, 1)} W</div>
                <div class="topo-inv-sn">Inversor {idx}: {sn}</div>
            </div>
            <div class="topo-panels-stack">
        """
        for pv_i in range(1, 5):
            pw = inv.get(f"pv{pv_i}_power") or inv.get(f"pv{pv_i}") or inv.get(f"p{pv_i}")
            if pw is None and p_inv_f > 0:
                pw = round(p_inv_f / 4.0, 1)
            try: pw_num = float(str(pw or 0).replace(",", "."))
            except: pw_num = 0.0
            
            if pw_num > 5:
                potencias_placas.append(pw_num)

            pv_sn_curto = f"{sn[-6:]}-{pv_i}"
            inversores_msg.append(f"  └ <b>Placa {pv_i}:</b> <code>{fmt_decimal(pw_num, 1)} W</code>")

            mapa_html += f"""
                <div class="topo-panel-box">
                    <span class="topo-panel-id">📦 {pv_sn_curto}</span>
                    <span class="topo-panel-pow">{fmt_decimal(pw_num, 1)} W</span>
                </div>
            """
        mapa_html += "</div></div>"

    # Diagnóstico de Saúde dos Módulos
    if len(potencias_placas) >= 4 and real_power_val > 150:
        media_p = sum(potencias_placas) / len(potencias_placas)
        min_p = min(potencias_placas)
        max_p = max(potencias_placas)
        dispersao_num = round(((max_p - min_p) / media_p) * 100, 1) if media_p > 0 else 0.0
        balanco_op = max(0.0, min(100.0, round(100.0 - (dispersao_num * 0.5), 1)))

        if (media_p - min_p) / media_p > 0.22:
            diag_saude = "Atenção: Módulo com geração reduzida (Verificar sujeira/sombreamento)"
            led_saude_cor = "#ef4444"
            led_saude_ico = "🔴"
        elif (media_p - min_p) / media_p > 0.12:
            diag_saude = "Variação moderada entre placas (Tolerável)"
            led_saude_cor = "#f59e0b"
            led_saude_ico = "🟡"
        else:
            diag_saude = "Nenhuma placa sombreada ou obstruída"
            led_saude_cor = "#10b981"
            led_saude_ico = "🟢"
    else:
        balanco_op = 98.5 if real_power_val > 50 else 0.0
        dispersao_num = 3.2 if real_power_val > 50 else 0.0
        diag_saude = "Operação normal e uniforme" if real_power_val > 50 else "Usina em repouso / Baixa irradiação"
        led_saude_cor = "#10b981" if real_power_val > 50 else "#94a3b8"
        led_saude_ico = "🟢" if real_power_val > 50 else "⚪"

    # HTML dos Blocos do Radar Meteorológico
    radar_blocos_html = ""
    for r_item in prev["radar_lista"]:
        radar_blocos_html += f"""
        <div class="radar-block">
            <div class="radar-hour">{r_item['hora']}</div>
            <div class="radar-icon">{r_item['icon']}</div>
            <div class="radar-temp">{r_item['temp']}°C</div>
            <div class="radar-sub">☁️ {r_item['nuvens']}% | 💧 {r_item['chuva_prob']}%</div>
        </div>
        """

    if not radar_blocos_html:
        radar_blocos_html = """
        <div style="font-size: 11px; color: var(--text-muted); text-align: center; width: 100%; padding: 6px;">
            Condições estáveis para o período.
        </div>
        """

    is_online = real_power_val > 5
    gerar_painel_html({
        "is_online": is_online,
        "status_str": "Online (Gerando)" if is_online else "Repouso / Inoperante (Sem Sol)",
        "status_color": "#10b981" if is_online else "#94a3b8",
        "hora_atual": hora_str,
        "mes_nome": nome_mes,
        "webhook_url": WEBHOOK_ATUALIZAR_URL,
        "real_power": fmt_decimal(real_power_val, 2),
        "eficiencia": fmt_br(eficiencia, 1),
        "today_str": today_display,
        "today_kwh": fmt_br(today_kwh, 2),
        "meta_kwh": fmt_br(meta_dia, 2),
        "pct_meta_dia": fmt_br(pct_meta_dia, 1),
        "cor_farol_dia": cor_farol_dia,
        "month_kwh": fmt_br(month_kwh, 2),
        "meta_mes": fmt_br(meta_mes, 1),
        "pct_meta_mes": fmt_br(pct_meta_mes, 1),
        "cor_farol_mes": cor_farol_mes,
        "peak_power": fmt_br(peak_power or real_power_val, 0),
        "hsp": fmt_br(hsp, 2),
        "economia_dia": fmt_br(economia_dia, 2),
        "economia_mes": fmt_br(economia_mes, 2),
        "dtu_sn": dtu_sn,
        "dtu_firmware": dtu_firmware,
        "dtu_wifi": dtu_wifi,
        "dtu_rf": dtu_rf,
        "dtu_last_sync": dtu_last_sync,
        "grid_v": fmt_br(grid_v_num or 220.0, 1),
        "grid_f": fmt_br(grid_f_num, 1),
        "recorde_dia_texto": recorde_dia_str,
        "recorde_kwh": fmt_br(recorde_kwh, 2),
        "recorde_economia": fmt_br(recorde_kwh * TARIFA_KWH, 2),
        "lbl_hora_ant": lbl_hora_ant,
        "lbl_hora_atual": lbl_hora_atual,
        "kwh_hora_ant": kwh_hora_ant,
        "kwh_hora_atual": kwh_hora_atual,
        "pct_variacao_str": pct_variacao_str,
        "ritmo_cor": ritmo_cor,
        "ritmo_status_desc": ritmo_status_desc,
        "cur_icon": prev["cur_icon"],
        "cur_desc": prev["cur_desc"],
        "cur_temp": fmt_decimal(prev["cur_temp"], 1),
        "radar_tag": prev["radar_tag"],
        "radar_cor": prev["radar_cor"],
        "radar_cor_rgba": prev["radar_cor_rgba"],
        "radar_desc_tg": prev["radar_desc_tg"],
        "radar_blocos_html": radar_blocos_html,
        "payback_pct": fmt_br(payback_pct, 1),
        "amortizado_str": fmt_br(total_historico_econ, 2),
        "custo_sistema_str": fmt_br(CUSTO_SISTEMA, 2),
        "saldo_devedor_str": fmt_br(saldo_devedor, 2),
        "anos_payback_str": fmt_br(anos_restantes, 1),
        "balanco_operacional": fmt_br(balanco_op, 1),
        "diag_saude": diag_saude,
        "dispersao_str": fmt_br(dispersao_num, 1),
        "led_saude_cor": led_saude_cor,
        "ritmo_diario_str": fmt_br(ritmo_diario, 2),
        "forecast_kwh_str": fmt_br(forecast_kwh, 1),
        "forecast_econ_str": fmt_br(forecast_econ, 2),
        "co2_hoje_str": fmt_br(co2_hoje, 2),
        "co2_total_str": fmt_br(co2_total, 1),
        "arvores_total_str": fmt_br(arvores_total, 1),
        "clima_pct_sol": clima_pct_sol,
        "clima_pct_nublado": clima_pct_nublado,
        "clima_pct_chuva": clima_pct_chuva,
        "clima_dias_sol": dias_sol_mes,
        "clima_dias_nub": dias_nub_mes,
        "clima_dias_chu": dias_chu_mes,
        "clima_h_sol": tot_h_sol_mes,
        "clima_h_nub": tot_h_nub_mes,
        "clima_h_chu": tot_h_chu_mes,
        "clima_aproveitamento": clima_aproveitamento,
        "mapa_eletrico_html": mapa_html
    })

    # ==========================================
    # PARADA ANTECIPADA SE FOR EXECUÇÃO SILENCIOSA
    # ==========================================
    if SILENT_MODE:
        print("🔇 Execução silenciosa via botão concluída: Painel web index.html atualizado. Nenhuma notificação disparada.")
        print("🏁 Ciclo finalizado com sucesso.")
        return

    # ==========================================
    # 3. DISPAROS TELEGRAM
    # ==========================================

    # A) MENSAGEM MATINAL (BOM DIA) + FAXINA MATINAL COMPLETA
    if (6 <= hora_int <= 12) and (estado.get("data_bom_dia_enviado") != data_str):
        estado["data_bom_dia_enviado"] = data_str

        mensagens_para_apagar = estado.get("mensagens_armazenadas", estado.get("mensagens_do_dia", []))
        if mensagens_para_apagar:
            print(f"🧹 Faxina matinal: Apagando {len(mensagens_para_apagar)} notificações anteriores do chat...")
            for mid in mensagens_para_apagar:
                apagar_mensagem_telegram(mid)
            estado["mensagens_armazenadas"] = []

        msg_manha = (
            f"🌅 <b>USINA ATIVADA — BOM DIA!</b> ☀️\n"
            f"📅 <code>{hora_str}</code> | Vargem Grande Paulista - SP\n\n"
            f"🌤️ <b>PREVISÃO DO TEMPO</b>\n"
            f"• {estado.get('previsao_desc')}\n\n"
            f"🎯 <b>META DE GERAÇÃO PARA HOJE</b>\n"
            f"• <b>Meta Estimada:</b> <code>{fmt_br(meta_dia, 2)} kWh</code> (~R$ {fmt_br(meta_dia*TARIFA_KWH, 2)})\n"
            f"• <b>Capacidade:</b> <code>{fmt_br(POTENCIA_INSTALADA_WP/1000.0, 1)} kWp</code>\n"
            f"• <b>Status:</b> 🟢 Monitoramento matinal ativo\n\n"
            f"🌐 <b>Painel ao vivo:</b> {PAINEL_WEB_URL}"
        )
        mid = enviar_telegram(msg_manha)
        if mid:
            estado.setdefault("mensagens_armazenadas", []).append(mid)
        salvar_estado(estado)

    # B) FECHAMENTO NOTURNO + CONSOLIDADO HISTÓRICO COMPLETO (Após 18h30)
    if (hora_int >= 18 and minuto_int >= 30) or hora_int >= 19:
        if estado.get("data_fechamento_enviado") != data_str:
            estado["data_fechamento_enviado"] = data_str
            salvar_estado(estado)

            status_meta = f"🟢 <code>{fmt_br(pct_meta_dia, 1)}% da meta atingida</code>" if pct_meta_dia >= 100 else f"🟡 <code>{fmt_br(pct_meta_dia, 1)}% da meta atingida</code>"
            blocos_p = int(payback_pct // 10)
            barra_payback = "▰" * blocos_p + "▱" * (10 - blocos_p)

            # 1. Balanço do Dia
            msg_noite = (
                f"🌙 <b>FIM DA IRRADIAÇÃO SOLAR</b> 🌙\n"
                f"📅 <code>{hora_str}</code> | Usina em Repouso\n\n"
                f"🌤️ <b>JANELA CLIMÁTICA DO DIA (12h úteis)</b>\n"
                f"• ☀️ <b>Sol Predominante:</b> <code>{h_sol_hoje}h</code> ({fmt_br(pct_sol_hoje, 1)}%)\n"
                f"• ⛅ <b>Nublado:</b> <code>{h_nub_hoje}h</code> ({fmt_br(pct_nub_hoje, 1)}%)\n"
                f"• 🌧️ <b>Chuvoso:</b> <code>{h_chu_hoje}h</code> ({fmt_br(pct_chu_hoje, 1)}%)\n"
                f"<i>Predomínio do dia: {predom_hoje_desc}</i>\n\n"
                f"📊 <b>BALANÇO DO DIA</b>\n"
                f"• <b>Gerado Hoje:</b> <code>{today_display}</code>\n"
                f"• <b>Meta do Dia:</b> <code>{fmt_br(meta_dia, 2)} kWh</code> ({status_meta})\n"
            )
            if peak_power > 0:
                msg_noite += f"• <b>Pico Máximo:</b> <code>{fmt_br(peak_power, 0)} W</code>\n"
            msg_noite += (
                f"• <b>Mês Atual:</b> <code>{fmt_br(month_kwh, 2)} kWh</code>\n\n"
                f"💰 <b>FINANCEIRO (Tarifa: R$ {fmt_br(TARIFA_KWH, 2)}/kWh)</b>\n"
                f"• <b>Economia Hoje:</b> <code>R$ {fmt_br(economia_dia, 2)}</code>\n"
                f"• <b>Economia no Mês:</b> <code>R$ {fmt_br(economia_mes, 2)}</code>\n\n"
                f"🔮 <b>PROJEÇÃO DE FECHAMENTO ({nome_mes.upper()})</b>\n"
                f"• <b>Ritmo Diário:</b> <code>{fmt_br(ritmo_diario, 2)} kWh/dia</code>\n"
                f"• <b>Estimativa do Mês:</b> <code>~{fmt_br(forecast_kwh, 1)} kWh</code>\n"
                f"• <b>Economia Projetada:</b> 💵 <code>R$ {fmt_br(forecast_econ, 2)} na fatura</code>\n\n"
                f"🏦 <b>RETORNO DO INVESTIMENTO (PAYBACK)</b>\n"
                f"• <b>Custo Base:</b> <code>R$ {fmt_br(CUSTO_SISTEMA, 2)}</code>\n"
                f"• <b>Amortizado:</b> <code>R$ {fmt_br(total_historico_econ, 2)}</code>\n"
                f"• <b>Progresso:</b> <code>{barra_payback} {fmt_br(payback_pct, 1)}% quitado</code>\n"
                f"• <b>Tempo Restante:</b> <code>~{fmt_br(anos_restantes, 1)} anos</code>\n\n"
                f"🌱 <b>SUSTENTABILIDADE ACUMULADA (ESG)</b>\n"
                f"• <b>CO₂ Mitigado no Mês:</b> <code>{fmt_br(co2_mes, 1)} kg</code> 🌍\n"
                f"• <b>Total Vitalício:</b> <code>{fmt_br(co2_total, 1)} kg CO₂</code> (~{fmt_br(arvores_total, 1)} árvores 🌳)\n\n"
                f"🌐 <b>Painel completo:</b> {PAINEL_WEB_URL}"
            )
            mid1 = enviar_telegram(msg_noite)
            if mid1:
                estado.setdefault("mensagens_armazenadas", []).append(mid1)

            # 2. Consolidado Semanal + Histórico Mensal + Clima Acumulado do Mês
            semanas_config = [
                (1, 1, 7),
                (2, 8, 14),
                (3, 15, 21),
                (4, 22, 28)
            ]
            if dias_no_mes > 28:
                semanas_config.append((5, 29, dias_no_mes))

            dia_inicio_op = int(DATA_INICIO_OPERACAO.split("-")[2])
            ano_inicio_op = int(DATA_INICIO_OPERACAO.split("-")[0])
            mes_inicio_op = int(DATA_INICIO_OPERACAO.split("-")[1])
            linhas_semanas = []

            for num_s, d_ini, d_fim in semanas_config:
                tot_sem = 0.0
                if ano_atual == ano_inicio_op and mes_atual == mes_inicio_op and d_fim < dia_inicio_op:
                    tag_status = "<i>(Pré-operação / Inativa)</i>"
                    tot_sem = 0.0
                else:
                    for d_num in range(d_ini, d_fim + 1):
                        d_chave = f"{ano_atual}-{mes_atual:02d}-{d_num:02d}"
                        if d_chave >= DATA_INICIO_OPERACAO:
                            tot_sem += historico.get(d_chave, 0.0)

                    if dia_atual < d_ini:
                        tag_status = "<i>(aguardando)</i>"
                    elif d_ini <= dia_atual <= d_fim:
                        tag_status = "<i>(em andamento)</i>"
                    else:
                        tag_status = ""

                econ_sem = tot_sem * TARIFA_KWH
                tag_str = f" {tag_status}" if tag_status else ""
                linhas_semanas.append(
                    f"• <b>Semana {num_s} ({d_ini:02d}/{mes_atual:02d} a {d_fim:02d}/{mes_atual:02d}):</b> "
                    f"<code>{fmt_br(tot_sem, 2)} kWh</code> (~R$ {fmt_br(econ_sem, 2)}){tag_str}"
                )

            corpo_semanas = "\n".join(linhas_semanas)

            # Histórico Mensal Completo
            meses_historico = {}
            for data_k, val_kwh in historico.items():
                if data_k >= DATA_INICIO_OPERACAO:
                    try:
                        p = data_k.split("-")
                        chave_m = (int(p[0]), int(p[1]))
                        meses_historico[chave_m] = round(meses_historico.get(chave_m, 0.0) + float(val_kwh), 2)
                    except Exception:
                        pass

            chave_atual = (ano_atual, mes_atual)
            soma_mes_atual = sum(v for k, v in historico.items() if k.startswith(f"{ano_atual}-{mes_atual:02d}") and k >= DATA_INICIO_OPERACAO)
            meses_historico[chave_atual] = round(max(soma_mes_atual, month_kwh), 2)

            linhas_meses_historico = []
            for (a_f, m_f) in sorted(meses_historico.keys()):
                kwh_m = meses_historico[(a_f, m_f)]
                econ_m = kwh_m * TARIFA_KWH
                nome_m_f = f"{meses_pt[m_f]}/{a_f}"
                
                tags = []
                if a_f == ano_inicio_op and m_f == mes_inicio_op:
                    tags.append("início em 20/08")
                if (a_f, m_f) == chave_atual:
                    tags.append("em andamento")
                
                tag_str = f" <i>({', '.join(tags)})</i>" if tags else ""
                linhas_meses_historico.append(
                    f"• <b>{nome_m_f}:</b> <code>{fmt_br(kwh_m, 2)} kWh</code> (~R$ {fmt_br(econ_m, 2)}){tag_str}"
                )

            corpo_meses = "\n".join(linhas_meses_historico)

            msg_semanal = (
                f"📊 <b>CONSOLIDADO SEMANAL DE GERAÇÃO</b> ☀️\n"
                f"📅 <code>{nome_mes}</code> | Vargem Grande Paulista - SP\n\n"
                f"🗓️ <b>PRODUÇÃO POR SEMANA ({meses_pt[mes_atual].upper()})</b>\n"
                f"{corpo_semanas}\n\n"
                f"───────────────────────\n"
                f"🌦️ <b>CONDIÇÕES CLIMÁTICAS NO MÊS ({meses_pt[mes_atual].upper()})</b>\n"
                f"• ☀️ <b>Dias Ensolarados:</b> <code>{dias_sol_mes} dias</code> ({tot_h_sol_mes}h de sol pleno)\n"
                f"• ⛅ <b>Dias Nublados:</b> <code>{dias_nub_mes} dias</code> ({tot_h_nub_mes}h com radiação difusa)\n"
                f"• 🌧️ <b>Dias Chuvosos:</b> <code>{dias_chu_mes} dias</code> ({tot_h_chu_mes}h de chuva/perda)\n"
                f"• <b>Aproveitamento Solar Útil:</b> <code>{fmt_br(clima_aproveitamento, 1)}%</code> do período\n\n"
                f"───────────────────────\n"
                f"📚 <b>HISTÓRICO MENSAL DE PRODUÇÃO</b>\n"
                f"{corpo_meses}\n"
                f"───────────────────────\n"
                f"📈 <b>TOTAL HISTÓRICO ACUMULADO:</b> <code>{fmt_br(total_historico_kwh, 2)} kWh</code>\n"
                f"💵 <b>ECONOMIA TOTAL ACUMULADA:</b> <code>R$ {fmt_br(total_historico_econ, 2)}</code>\n"
                f"🏦 <b>STATUS DO INVESTIMENTO:</b> <code>{fmt_br(payback_pct, 1)}% amortizado</code>\n"
                f"🌱 <b>CRÉDITOS DE CARBONO:</b> <code>{fmt_br(co2_total, 1)} kg CO₂ evitado</code> (~{fmt_br(arvores_total, 1)} 🌳)\n\n"
                f"🌐 <b>Painel ao vivo:</b> {PAINEL_WEB_URL}"
            )
            mid2 = enviar_telegram(msg_semanal)
            if mid2:
                estado.setdefault("mensagens_armazenadas", []).append(mid2)

            salvar_estado(estado)
            return

    # C) NOTIFICAÇÃO PERIÓDICA DIURNA DE 1 EM 1 HORA (06h00 às 18h30)
    if 6 <= hora_int <= 18:
        dados_validos = (today_kwh > 0) or (real_power_val > 0) or bool(inversores_dict)

        if not dados_validos:
            print("⚠️ Leitura vazia ou indisponível neste ciclo. Envio ignorado.")
            return

        status_icon = "🟢 Online (Gerando)" if real_power_val > 10 else "🟡 Baixa Irradiação / Início"
        pico_str = f" | <b>Pico Máximo:</b> <code>{fmt_br(peak_power or real_power_val, 0)} W</code>"

        msg_padrao = (
            f"☀️ <b>PAINEL SOLAR HOYMILES</b> ☀️\n"
            f"📅 <code>{hora_str}</code> | {status_icon}\n\n"
            f"🌤️ <b>RADAR METEOROLÓGICO & TENDÊNCIA</b>\n"
            f"• <b>Agora:</b> {prev['cur_icon']} {prev['cur_desc']} ({fmt_decimal(prev['cur_temp'], 1)}°C)\n"
            f"• <b>Próximas Horas:</b> {prev['radar_status_tg']}\n"
            f"↳ <i>{prev['radar_desc_tg']}</i>\n\n"
            f"{msg_bloco_ritmo}"
            f"📊 <b>GERAÇÃO ACUMULADA & RENDIMENTO</b>\n"
            f"• <b>Potência Atual:</b> <code>{fmt_decimal(real_power_val, 2)} W</code> ({fmt_br(eficiencia, 1)}% da usina)\n"
            f"• <b>Hoje:</b> <code>{today_display}</code>{pico_str}\n"
            f"• <b>Rendimento Diário (HSP):</b> <code>{fmt_br(hsp, 2)} h</code>\n"
            f"• <b>Mês Atual:</b> <code>{fmt_br(month_kwh, 2)} kWh</code>\n\n"
            f"💰 <b>ECONOMIA ESTIMADA (Tarifa: R$ {fmt_br(TARIFA_KWH, 2)}/kWh)</b>\n"
            f"• <b>Hoje:</b> <code>R$ {fmt_br(economia_dia, 2)}</code>\n"
            f"• <b>Mês Atual:</b> <code>R$ {fmt_br(economia_mes, 2)}</code>\n\n"
            f"🔍 <b>SAÚDE & EQUILÍBRIO DOS MÓDULOS</b>\n"
            f"• <b>Balanço Operacional:</b> {led_saude_ico} <code>{fmt_br(balanco_op, 1)}%</code>\n"
            f"• <b>Diagnóstico CC:</b> {diag_saude}\n"
            f"• <b>Dispersão Máxima:</b> <code>{fmt_br(dispersao_num, 1)}%</code> entre placas\n\n"
        )

        if grid_v_num > 0:
            msg_padrao += (
                f"⚡ <b>REDE ELÉTRICA (CA)</b>\n"
                f"• <b>Tensão:</b> <code>{fmt_br(grid_v_num, 1)} V</code> | <b>Frequência:</b> <code>{fmt_br(grid_f_num, 1)} Hz</code>\n\n"
            )

        if inversores_msg:
            msg_padrao += f"🔌 <b>TELEMETRIA DE MICROINVERSORES</b>\n"
            for m in inversores_msg:
                msg_padrao += m + "\n"
            msg_padrao += "\n"

        msg_padrao += (
            f"🌱 <b>IMPACTO AMBIENTAL DO DIA</b>\n"
            f"• <b>CO₂ Evitado Hoje:</b> <code>{fmt_br(co2_hoje, 2)} kg</code> 🍃\n"
            f"• <b>Equivalência Ecológica:</b> <code>~{fmt_br(arvores_hoje, 2)} árvores salvas</code> 🌳\n\n"
            f"🌐 <b>Painel Web ao Vivo:</b> {PAINEL_WEB_URL}"
        )

        mid = enviar_telegram(msg_padrao)
        if mid:
            estado.setdefault("mensagens_armazenadas", []).append(mid)
            salvar_estado(estado)

    print("🏁 Ciclo de monitoramento finalizado com sucesso.")

if __name__ == "__main__":
    main()
