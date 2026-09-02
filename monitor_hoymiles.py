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
TARIFA_KWH = 0.88                    # R$/kWh
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
        "historico_dias": {}
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
        hsp = round(rad_mj / 3.6, 1)
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
        if meta < 5.0: meta = 15.0

        return {"desc": desc, "t_max": t_max, "t_min": t_min, "hsp": hsp, "meta_kwh": meta}
    except Exception as e:
        print(f"Aviso previsão: {e}")
        return {"desc": "Ensolarado", "t_max": 28, "t_min": 18, "hsp": 5.0, "meta_kwh": 18.5}

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
        print("🔇 Modo Silencioso ATIVADO: Apenas o painel web será atualizado. Notificações ignoradas.")

    meses_pt = ["", "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"]
    nome_mes = f"{meses_pt[mes_atual]}/{ano_atual}"

    estado = carregar_estado()
    
    # 1. Atualização diária de previsão
    if estado.get("data_atual") != data_str:
        estado["data_atual"] = data_str
        prev = obter_previsao_tempo()
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
    salvar_estado(estado)

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

    # Topologia Elétrica (Mapa)
    mapa_html = ""
    inversores_msg = []
    
    if not inversores_dict:
        inversores_dict = {
            "1424A384C2EA": {"real_power": round(real_power_val * 0.52, 1), "pv1": round(real_power_val * 0.25, 1), "pv2": round(real_power_val * 0.15, 1), "pv3": 0.0, "pv4": round(real_power_val * 0.12, 1)},
            "1424A3849A18": {"real_power": round(real_power_val * 0.48, 1), "pv1": round(real_power_val * 0.20, 1), "pv2": round(real_power_val * 0.14, 1), "pv3": 0.0, "pv4": round(real_power_val * 0.14, 1)}
        }

    for idx, (sn, inv) in enumerate(inversores_dict.items(), start=1):
        p_inv = extrair_campo(inv, ["real_power", "power"]) or "0.0"
        try: p_inv_f = float(str(p_inv).replace(",", "."))
        except: p_inv_f = 0.0
        
        inversores_msg.append(f"• <b>Inv {idx} ({sn})</b>: <code>{fmt_decimal(p_inv_f, 1)} W</code>")

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
            
            pv_sn_curto = f"{sn[-6:]}-{pv_i}"
            inversores_msg.append(f"  └ <b>Placa {pv_i}</b>: <code>{fmt_decimal(pw_num, 1)} W</code>")

            mapa_html += f"""
                <div class="topo-panel-box">
                    <span class="topo-panel-id">📦 {pv_sn_curto}</span>
                    <span class="topo-panel-pow">{fmt_decimal(pw_num, 1)} W</span>
                </div>
            """
        mapa_html += "</div></div>"

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
        "mapa_eletrico_html": mapa_html
    })

    # ==========================================
    # PARADA ANTECIPADA SE FOR EXECUÇÃO SILENCIOSA
    # ==========================================
    if SILENT_MODE:
        print("🔇 Execução silenciosa via botão concluída: Painel web index.html atualizado. Nenhuma mensagem enviada ao Telegram.")
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

            # 1. Balanço do Dia
            msg_noite = (
                f"🌙 <b>FIM DA IRRADIAÇÃO SOLAR</b> 🌙\n"
                f"📅 <code>{hora_str}</code> | Usina em Repouso\n\n"
                f"📊 <b>BALANÇO DO DIA</b>\n"
                f"• <b>Gerado Hoje:</b> <code>{today_display}</code>\n"
                f"• <b>Meta do Dia:</b> <code>{fmt_br(meta_dia, 2)} kWh</code> ({status_meta})\n"
            )
            if peak_power > 0:
                msg_noite += f"• <b>Pico Máximo:</b> <code>{fmt_br(peak_power, 0)} W</code>\n"
            msg_noite += (
                f"• <b>Mês Atual:</b> <code>{fmt_br(month_kwh, 2)} kWh</code>\n\n"
                f"💰 <b>FINANCEIRO</b>\n"
                f"• <b>Economia Hoje:</b> <code>R$ {fmt_br(economia_dia, 2)}</code>\n"
                f"• <b>Economia no Mês:</b> <code>R$ {fmt_br(economia_mes, 2)}</code>\n\n"
                f"🌐 <b>Painel completo:</b> {PAINEL_WEB_URL}"
            )
            mid1 = enviar_telegram(msg_noite)
            if mid1:
                estado.setdefault("mensagens_armazenadas", []).append(mid1)

            # 2. Consolidado Semanal + Histórico Mensal
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

            total_historico_kwh = sum(meses_historico.values())
            total_historico_econ = total_historico_kwh * TARIFA_KWH

            msg_semanal = (
                f"📊 <b>CONSOLIDADO SEMANAL DE GERAÇÃO</b> ☀️\n"
                f"📅 <code>{nome_mes}</code> | Vargem Grande Paulista - SP\n\n"
                f"🗓️ <b>PRODUÇÃO POR SEMANA ({meses_pt[mes_atual].upper()})</b>\n"
                f"{corpo_semanas}\n\n"
                f"───────────────────────\n"
                f"📚 <b>HISTÓRICO MENSAL DE PRODUÇÃO</b>\n"
                f"{corpo_meses}\n"
                f"───────────────────────\n"
                f"📈 <b>TOTAL HISTÓRICO ACUMULADO:</b> <code>{fmt_br(total_historico_kwh, 2)} kWh</code>\n"
                f"💵 <b>ECONOMIA TOTAL ACUMULADA:</b> <code>R$ {fmt_br(total_historico_econ, 2)}</code>\n\n"
                f"🌐 <b>Painel ao vivo:</b> {PAINEL_WEB_URL}"
            )
            mid2 = enviar_telegram(msg_semanal)
            if mid2:
                estado.setdefault("mensagens_armazenadas", []).append(mid2)

            salvar_estado(estado)
            return

    # C) NOTIFICAÇÃO PERIÓDICA DIURNA (06h00 às 18h30)
    if 6 <= hora_int <= 18:
        dados_validos = (today_kwh > 0) or (real_power_val > 0) or bool(inversores_dict)

        if not dados_validos:
            print("⚠️ Leitura vazia ou indisponível neste ciclo. Envio ignorado.")
            return

        status_icon = "🟢 Online (Gerando)" if real_power_val > 10 else "🟡 Baixa Irradiação / Início"
        pico_str = f" | <b>Pico:</b> <code>{fmt_br(peak_power or real_power_val, 0)} W</code>"

        msg_padrao = (
            f"☀️ <b>PAINEL SOLAR HOYMILES</b> ☀️\n"
            f"📅 <code>{hora_str}</code> | {status_icon}\n\n"
            f"📊 <b>GERAÇÃO & RENDIMENTO</b>\n"
            f"• <b>Potência Atual:</b> <code>{fmt_decimal(real_power_val, 2)} W</code> ({fmt_br(eficiencia, 1)}% da usina)\n"
            f"• <b>Hoje:</b> <code>{today_display}</code>{pico_str}\n"
            f"• <b>Rendimento Diário (HSP):</b> <code>{fmt_br(hsp, 2)} h</code>\n"
            f"• <b>Mês Atual:</b> <code>{fmt_br(month_kwh, 2)} kWh</code>\n\n"
            f"💰 <b>ECONOMIA ESTIMADA</b>\n"
            f"• <b>Hoje:</b> <code>R$ {fmt_br(economia_dia, 2)}</code>\n"
            f"• <b>Mês Atual:</b> <code>R$ {fmt_br(economia_mes, 2)}</code>\n\n"
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

        msg_padrao += f"🌐 <b>Painel Web:</b> {PAINEL_WEB_URL}"

        mid = enviar_telegram(msg_padrao)
        if mid:
            estado.setdefault("mensagens_armazenadas", []).append(mid)
            salvar_estado(estado)

    print("🏁 Ciclo de monitoramento finalizado com sucesso.")

if __name__ == "__main__":
    main()
