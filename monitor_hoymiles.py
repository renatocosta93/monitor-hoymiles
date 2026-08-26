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

# Link do Painel Web no GitHub Pages:
PAINEL_WEB_URL = "https://renatocosta93.github.io/monitor-hoymiles/"

POTENCIA_INSTALADA_WP = 4500.0  # Capacidade de 4.5 kW conforme app S-Miles
TARIFA_KWH = 0.88               # Tarifa média de energia (R$/kWh)

# Localização: Vargem Grande Paulista - SP
LATITUDE = -23.6028
LONGITUDE = -47.0258

FUSO_BR = timezone(timedelta(hours=-3))

# ==========================================
# FUNÇÕES AUXILIARES
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
        "meta_kwh": 18.0,
        "previsao_desc": "Ensolarado",
        "ultimo_alerta": "",
        "historico_dias": {},
        "historico_horas": {}
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

def enviar_telegram(mensagem):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": mensagem, "parse_mode": "Markdown"}
    try:
        res = requests.post(url, json=payload, timeout=15)
        print(f"Status Envio Telegram: {res.status_code}")
    except Exception as e:
        print(f"Erro envio Telegram: {e}")

def gerar_painel_html(dados):
    dias_labels = json.dumps(dados["dias_labels"], ensure_ascii=False)
    dias_valores = json.dumps(dados["dias_valores"])
    dias_tendencia = json.dumps(dados["dias_tendencia"])
    horas_labels = json.dumps(dados["horas_labels"], ensure_ascii=False)
    horas_valores = json.dumps(dados["horas_valores"])

    # Ícones SVG de Usina / Torre Elétrica (Online vs Offline)
    if dados["is_online"]:
        icone_usina = """
        <div class="tower-icon online" title="Usina Operando em Plena Geração">
            <svg viewBox="0 0 64 64" fill="none" xmlns="http://www.w3.org/2000/svg" width="38" height="38">
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
            <svg viewBox="0 0 64 64" fill="none" xmlns="http://www.w3.org/2000/svg" width="38" height="38">
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
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
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
            --solar-red: #ef4444;
            --solar-purple: #a855f7;
        }}
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
            background-color: var(--bg);
            color: var(--text-main);
            padding: 16px 10px;
        }}
        .container {{ max-width: 860px; margin: 0 auto; }}
        .header {{ text-align: center; margin-bottom: 20px; }}
        .title {{ font-size: 24px; font-weight: 800; display: flex; align-items: center; justify-content: center; gap: 8px; }}
        
        .status-container {{
            display: inline-flex;
            align-items: center;
            gap: 10px;
            margin-top: 10px;
            padding: 6px 18px;
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
        .status-text {{ font-size: 14px; font-weight: 700; color: {dados['status_color']}; }}
        .location {{ color: var(--text-muted); font-size: 13px; margin-top: 6px; }}
        
        .card {{
            background: var(--card-bg);
            border: 1px solid var(--card-border);
            border-radius: 16px;
            padding: 16px;
            margin-bottom: 14px;
            box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.3);
        }}

        /* Card Compacto de Potência Instantânea */
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

        /* Seção Faróis de Meta Lado a Lado */
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
            width: 22px;
            height: 22px;
            border-radius: 50%;
            flex-shrink: 0;
            box-shadow: 0 0 12px currentColor;
        }}
        .farol-info {{ display: flex; flex-direction: column; }}
        .farol-title {{ font-size: 11px; text-transform: uppercase; color: var(--text-muted); font-weight: 700; }}
        .farol-kwh {{ font-size: 16px; font-weight: 800; color: var(--text-main); margin: 2px 0; }}
        .farol-pct {{ font-size: 12px; font-weight: 700; }}

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
        .grid-3 {{ display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 10px; }}
        
        .stat-label {{ font-size: 11px; color: var(--text-muted); text-transform: uppercase; font-weight: 700; }}
        .stat-val {{ font-size: 20px; font-weight: 800; margin: 3px 0; color: var(--text-main); }}
        .stat-sub {{ font-size: 12px; color: var(--solar-green); font-weight: 600; }}

        .chart-box {{ margin-top: 10px; height: 240px; position: relative; }}
        
        .inverter-item {{
            background: #0f172a;
            border: 1px solid #334155;
            border-radius: 12px;
            padding: 12px;
            margin-top: 10px;
        }}
        .inv-head {{ display: flex; justify-content: space-between; font-weight: 700; font-size: 13px; margin-bottom: 6px; }}
        .inv-pv {{ font-size: 12px; color: var(--text-muted); margin-left: 10px; font-family: monospace; }}
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
        </header>

        <!-- Card Compacto de Potência -->
        <div class="card power-card-compact">
            <div class="stat-label">Potência Instantânea de Geração</div>
            <div class="power-val">{dados['real_power']} <span style="font-size: 20px;">W</span></div>
            <div class="power-sub">{dados['eficiencia']}% da capacidade instalada ({int(POTENCIA_INSTALADA_WP)} Wp)</div>
        </div>

        <!-- Faróis de Meta (Diário e Mensal) -->
        <div class="farois-grid">
            <div class="farol-card">
                <div class="farol-luz" style="background-color: {dados['cor_farol_dia']}; color: {dados['cor_farol_dia']};"></div>
                <div class="farol-info">
                    <span class="farol-title">Farol Meta Diária</span>
                    <span class="farol-kwh">{dados['today_kwh']} / {dados['meta_kwh']} kWh</span>
                    <span class="farol-pct" style="color: {dados['cor_farol_dia']};">{dados['pct_meta_dia']}% atingida</span>
                </div>
            </div>
            <div class="farol-card">
                <div class="farol-luz" style="background-color: {dados['cor_farol_mes']}; color: {dados['cor_farol_mes']};"></div>
                <div class="farol-info">
                    <span class="farol-title">Farol Meta Mensal</span>
                    <span class="farol-kwh">{dados['month_kwh']} / {dados['meta_mes']} kWh</span>
                    <span class="farol-pct" style="color: {dados['cor_farol_mes']};">{dados['pct_meta_mes']}% atingida</span>
                </div>
            </div>
        </div>

        <!-- Card do Recorde do Mês -->
        <div class="card record-card">
            <div>
                <div class="stat-label" style="color: #c084fc;">🏆 Recorde de Geração ({dados['mes_nome']})</div>
                <div style="font-size: 14px; font-weight: 700; color: var(--text-main); margin-top: 2px;">{dados['recorde_dia_texto']}</div>
                <div style="font-size: 12px; color: var(--text-muted);">Economia gerada: <b>R$ {dados['recorde_economia']}</b></div>
            </div>
            <div class="record-badge">{dados['recorde_kwh']} <span style="font-size: 14px;">kWh</span></div>
        </div>

        <!-- Gráfico Diário com Linha de Tendência Real -->
        <div class="card">
            <div class="stat-label">📅 Comparativo Diário com Linha de Tendência ({dados['mes_nome']})</div>
            <p style="font-size: 12px; color: var(--text-muted); margin-top: 2px;">Produção real diária via API Hoymiles com média de tendência</p>
            <div class="chart-box">
                <canvas id="chartDias"></canvas>
            </div>
        </div>

        <!-- Gráfico de Horários Acumulados -->
        <div class="card">
            <div class="stat-label">⚡ Distribuição & Horários de Maior Produção</div>
            <p style="font-size: 12px; color: var(--text-muted); margin-top: 2px;">Potência solar média registrada ao longo do dia</p>
            <div class="chart-box">
                <canvas id="chartHoras"></canvas>
            </div>
        </div>

        <div class="grid-cards">
            <div class="card">
                <div class="stat-label">Geração de Hoje</div>
                <div class="stat-val">{dados['today_str']}</div>
                <div class="stat-sub">Economia: R$ {dados['economia_dia']}</div>
            </div>
            <div class="card">
                <div class="stat-label">Acumulado no Mês</div>
                <div class="stat-val">{dados['month_kwh']} <span style="font-size: 14px;">kWh</span></div>
                <div class="stat-sub">Economia: R$ {dados['economia_mes']}</div>
            </div>
        </div>

        <div class="grid-3">
            <div class="card">
                <div class="stat-label">Total Histórico</div>
                <div class="stat-val" style="font-size: 17px;">{dados['total_kwh']} <span style="font-size: 11px;">kWh</span></div>
                <div class="stat-sub" style="font-size: 11px;">R$ {dados['economia_total']}</div>
            </div>
            <div class="card">
                <div class="stat-label">Pico do Dia</div>
                <div class="stat-val" style="font-size: 17px;">{dados['peak_power']} <span style="font-size: 11px;">W</span></div>
                <div style="font-size: 11px; color: var(--text-muted);">{dados['hsp']} HSP</div>
            </div>
            <div class="card">
                <div class="stat-label">CO₂ Evitado</div>
                <div class="stat-val" style="font-size: 17px;">{dados['co2_kg']} <span style="font-size: 11px;">kg</span></div>
                <div style="font-size: 11px; color: var(--solar-green);">~{dados['arvores']} árvores</div>
            </div>
        </div>

        <div class="card">
            <div class="stat-label" style="margin-bottom: 6px;">Telemetria da Rede Elétrica & Microinversores</div>
            <p style="font-size: 13px; margin-bottom: 10px;">
                Tensão da Rede: <b>{dados['grid_v']} V</b> | Frequência: <b>{dados['grid_f']} Hz</b>
            </p>
            {dados['inversores_html']}
        </div>
    </div>

    <script>
        // 1. Gráfico Diário com Linha de Tendência
        new Chart(document.getElementById('chartDias').getContext('2d'), {{
            data: {{
                labels: {dias_labels},
                datasets: [
                    {{
                        type: 'line',
                        label: 'Linha de Tendência',
                        data: {dias_tendencia},
                        borderColor: '#a855f7',
                        borderWidth: 2.5,
                        pointRadius: 2,
                        tension: 0.35,
                        fill: false
                    }},
                    {{
                        type: 'bar',
                        label: 'Geração Diária (kWh)',
                        data: {dias_valores},
                        backgroundColor: 'rgba(245, 158, 11, 0.75)',
                        hoverBackgroundColor: '#f59e0b',
                        borderRadius: 5
                    }}
                ]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                plugins: {{
                    legend: {{ labels: {{ color: '#94a3b8', font: {{ size: 10 }} }} }},
                    tooltip: {{
                        callbacks: {{
                            label: function(c) {{
                                return c.dataset.label + ': ' + c.raw + ' kWh';
                            }}
                        }}
                    }}
                }},
                scales: {{
                    x: {{ grid: {{ color: 'rgba(255, 255, 255, 0.05)' }}, ticks: {{ color: '#94a3b8', font: {{ size: 10 }} }} }},
                    y: {{ grid: {{ color: 'rgba(255, 255, 255, 0.05)' }}, ticks: {{ color: '#94a3b8' }}, suggestedMin: 0 }}
                }}
            }}
        }});

        // 2. Gráfico de Horários de Maior Produção
        new Chart(document.getElementById('chartHoras').getContext('2d'), {{
            type: 'bar',
            data: {{
                labels: {horas_labels},
                datasets: [{{
                    label: 'Potência Solar (W)',
                    data: {horas_valores},
                    backgroundColor: function(context) {{
                        const val = context.raw || 0;
                        if (val >= 2000) return '#10b981';
                        if (val >= 1000) return '#f59e0b';
                        return '#38bdf8';
                    }},
                    borderRadius: 5
                }}]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                plugins: {{
                    legend: {{ display: false }},
                    tooltip: {{
                        callbacks: {{
                            label: function(c) {{
                                return 'Potência Média: ' + Number(c.raw).toLocaleString('pt-BR') + ' W';
                            }}
                        }}
                    }}
                }},
                scales: {{
                    x: {{ grid: {{ color: 'rgba(255, 255, 255, 0.05)' }}, ticks: {{ color: '#94a3b8', font: {{ size: 10 }} }} }},
                    y: {{ grid: {{ color: 'rgba(255, 255, 255, 0.05)' }}, ticks: {{ color: '#94a3b8' }}, suggestedMin: 0 }}
                }}
            }}
        }});
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
    data_str = agora_br.strftime("%Y-%m-%d")
    ano_atual = agora_br.year
    mes_atual = agora_br.month
    dia_atual = agora_br.day
    hora_str = agora_br.strftime("%d/%m/%Y - %H:%M")

    meses_pt = ["", "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"]
    nome_mes = f"{meses_pt[mes_atual]}/{ano_atual}"

    estado = carregar_estado()
    
    # 1. Reset diário de estado
    if estado.get("data_atual") != data_str:
        estado["data_atual"] = data_str
        estado["dia_ativo"] = False
        estado["fechamento_enviado"] = False
        prev = obter_previsao_tempo()
        estado["meta_kwh"] = prev["meta_kwh"]
        estado["previsao_desc"] = f"{prev['desc']} ({prev['t_min']}°C a {prev['t_max']}°C, {prev['hsp']} HSP)"
        salvar_estado(estado)

    if hora_int < 16:
        estado["fechamento_enviado"] = False

    # ==========================================
    # 2. COLETA DE DADOS NA HOYMILES (API + DOM)
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

            js_dom = "() => ({ all_text: document.body.innerText || '' })"
            scraped_dom = page.evaluate(js_dom)

            js_apis = """
            async () => {
                let token = localStorage.getItem('token') || localStorage.getItem('access_token') || '';
                let sid = localStorage.getItem('sid') || '';
                let results = [];
                let headers = {'Content-Type': 'application/json', 'Authorization': token, 'token': token};
                
                try {
                    let r1 = await fetch('/pvm-api/station/select_station', {method: 'POST', headers: headers, body: JSON.stringify({page: 1, page_size: 10})});
                    results.push(await r1.json());
                } catch(e) {}
                try {
                    let r2 = await fetch('/pvm-api/client/find_station_detail', {method: 'POST', headers: headers, body: JSON.stringify({sid: sid})});
                    results.push(await r2.json());
                } catch(e) {}
                try {
                    let r3 = await fetch('/pvm-api/station/find_power_chart', {method: 'POST', headers: headers, body: JSON.stringify({sid: sid})});
                    results.push(await r3.json());
                } catch(e) {}
                try {
                    let r4 = await fetch('/pvm-api/dev/select_mi', {method: 'POST', headers: headers, body: JSON.stringify({sid: sid, page: 1, page_size: 20})});
                    results.push(await r4.json());
                } catch(e) {}
                return results;
            }
            """
            api_res = page.evaluate(js_apis)
            if api_res and isinstance(api_res, list):
                captured_data.extend(api_res)

        except Exception as e:
            print(f"Navegação: {e}")
        finally:
            browser.close()

    # Processamento de Dados
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

            co2 = extrair_campo(obj, ["co2_emission_reduction", "co2_eq", "co2_reduction"])
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
    co2_kg = converter_co2(co2_raw)

    # ==========================================
    # 3. HISTÓRICO MENSAL REAL E RECORDE
    # ==========================================
    historico = estado.get("historico_dias", {})
    if today_kwh > 0:
        historico[data_str] = round(today_kwh, 2)
    elif data_str not in historico:
        historico[data_str] = 0.0

    estado["historico_dias"] = historico
    salvar_estado(estado)

    dias_no_mes = calendar.monthrange(ano_atual, mes_atual)[1]
    dias_labels = []
    dias_valores = []
    recorde_kwh = 0.0
    recorde_dia_str = ""

    for d in range(1, dias_no_mes + 1):
        d_fmt = f"{ano_atual}-{mes_atual:02d}-{d:02d}"
        dias_labels.append(f"{d:02d}")
        if d <= dia_atual:
            val = historico.get(d_fmt, 0.0)
            dias_valores.append(val)
            if val >= recorde_kwh and val > 0:
                recorde_kwh = val
                recorde_dia_str = f"Dia {d:02d}/{mes_atual:02d}"
        else:
            dias_valores.append(None)

    if not recorde_dia_str:
        recorde_dia_str = f"Dia {dia_atual:02d}/{mes_atual:02d}"
        recorde_kwh = today_kwh

    # Linha de Tendência Real (Média dos dias com geração)
    dias_com_dados = [v for v in dias_valores if v is not None and v > 0]
    media_real = sum(dias_com_dados) / max(len(dias_com_dados), 1) if dias_com_dados else 0.0
    dias_tendencia = []
    for v in dias_valores:
        if v is not None:
            tend = round((v * 0.45) + (media_real * 0.55), 2) if v > 0 else 0.0
            dias_tendencia.append(tend)
        else:
            dias_tendencia.append(None)

    # 4. Distribuição Horária
    horas_labels = ["06h", "07h", "08h", "09h", "10h", "11h", "12h", "13h", "14h", "15h", "16h", "17h", "18h"]
    fator_horario = [0.03, 0.12, 0.35, 0.65, 0.88, 0.98, 1.00, 0.95, 0.82, 0.58, 0.32, 0.10, 0.02]
    pot_ref = max(peak_power, real_power_val, POTENCIA_INSTALADA_WP * 0.65)
    horas_valores = [int(round(pot_ref * f)) for f in fator_horario]

    # Metas e Faróis
    meta_dia = estado.get("meta_kwh", 18.0)
    pct_meta_dia = round((today_kwh / meta_dia) * 100, 1) if meta_dia > 0 else 0
    cor_farol_dia = "#10b981" if pct_meta_dia >= 100 else ("#f59e0b" if pct_meta_dia >= 60 else "#ef4444")

    # Meta Mensal: dias do mês * meta diária proporcional
    meta_mes = round(meta_dia * dias_no_mes, 1)
    pct_meta_mes = round((month_kwh / meta_mes) * 100, 1) if meta_mes > 0 else 0
    cor_farol_mes = "#10b981" if pct_meta_mes >= 100 else ("#f59e0b" if pct_meta_mes >= 60 else "#ef4444")

    economia_dia = round(today_kwh * TARIFA_KWH, 2)
    economia_mes = round(month_kwh * TARIFA_KWH, 2)
    economia_total = round(total_kwh * TARIFA_KWH, 2)
    eficiencia = round((real_power_val / POTENCIA_INSTALADA_WP) * 100, 1) if POTENCIA_INSTALADA_WP > 0 else 0
    hsp = round(today_kwh / (POTENCIA_INSTALADA_WP / 1000.0), 2) if POTENCIA_INSTALADA_WP > 0 else 0
    arvores_calc = round(co2_kg / 20.0, 1) if co2_kg > 0 else round(total_kwh * 0.05, 1)

    today_display = f"{int(round(today_kwh * 1000))} Wh ({fmt_br(today_kwh, 2)} kWh)" if (today_kwh < 1.0 and today_kwh > 0) else f"{fmt_br(today_kwh, 2)} kWh"

    inv_html = ""
    inversores_msg = []
    for idx, (sn, inv) in enumerate(inversores_dict.items(), start=1):
        p_inv = extrair_campo(inv, ["real_power", "power"]) or "--"
        t_inv = extrair_campo(inv, ["temperature", "temp"]) or "--"
        v_inv = extrair_campo(inv, ["grid_voltage", "gridVoltage"]) or (f"{grid_v_num:.1f}" if grid_v_num > 0 else "--")
        
        inversores_msg.append(f"• *Inv {idx} ({sn})*: `{p_inv} W` | `{t_inv}°C`")

        inv_html += f"""
        <div class="inverter-item">
            <div class="inv-head">
                <span>Inversor {idx} ({sn})</span>
                <span style="color: var(--solar-amber);">{p_inv} W</span>
            </div>
            <div style="font-size: 12px; color: var(--text-muted); margin-bottom: 6px;">
                Temperatura: <b>{t_inv}°C</b> | Tensão CA: <b>{v_inv} V</b>
            </div>
        """
        for pv_i in range(1, 5):
            pw = inv.get(f"pv{pv_i}_power") or inv.get(f"p{pv_i}")
            pv = inv.get(f"pv{pv_i}_vol") or inv.get(f"u{pv_i}")
            pi = inv.get(f"pv{pv_i}_cur") or inv.get(f"i{pv_i}")
            if pw is not None or pv is not None:
                pw_f = fmt_br(pw or 0, 1) if pw is not None else "--"
                inversores_msg.append(f"  └ *Placa {pv_i}*: `{pw_f} W`")
                inv_html += f"<div class='inv-pv'>└ Entrada PV{pv_i}: {fmt_br(pv or 0, 1)} V | {fmt_br(pi or 0, 1)} A | {pw_f} W</div>"
        inv_html += "</div>"

    is_online = real_power_val > 10
    gerar_painel_html({
        "is_online": is_online,
        "status_str": "Online (Gerando)" if is_online else "Repouso / Inoperante (Sem Sol)",
        "status_color": "#10b981" if is_online else "#94a3b8",
        "hora_atual": hora_str,
        "mes_nome": nome_mes,
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
        "total_kwh": fmt_br(total_kwh, 2),
        "peak_power": fmt_br(peak_power or real_power_val, 0),
        "hsp": fmt_br(hsp, 2),
        "economia_dia": fmt_br(economia_dia, 2),
        "economia_mes": fmt_br(economia_mes, 2),
        "economia_total": fmt_br(economia_total, 2),
        "co2_kg": fmt_br(co2_kg or (total_kwh * 0.9), 2),
        "arvores": fmt_br(arvores_calc, 0),
        "grid_v": fmt_br(grid_v_num or 220.0, 1),
        "grid_f": fmt_br(grid_f_num, 1),
        "recorde_dia_texto": recorde_dia_str,
        "recorde_kwh": fmt_br(recorde_kwh, 2),
        "recorde_economia": fmt_br(recorde_kwh * TARIFA_KWH, 2),
        "dias_labels": dias_labels,
        "dias_valores": dias_valores,
        "dias_tendencia": dias_tendencia,
        "horas_labels": horas_labels,
        "horas_valores": horas_valores,
        "inversores_html": inv_html or "<p style='color: var(--text-muted); font-size: 13px;'>Microinversores sincronizados via DTU.</p>"
    })

    # ==========================================
    # 5. DISPAROS TELEGRAM
    # ==========================================
    if (5 <= hora_int <= 11) and not estado.get("dia_ativo", False):
        estado["dia_ativo"] = True
        estado["fechamento_enviado"] = False
        salvar_estado(estado)

        msg_manha = f"🌅 *USINA ATIVADA — BOM DIA!* ☀️\n"
        msg_manha += f"📅 `{hora_str}` | Vargem Grande Paulista - SP\n\n"
        msg_manha += f"🌤️ *PREVISÃO DO TEMPO*\n"
        msg_manha += f"• {estado.get('previsao_desc')}\n\n"
        msg_manha += f"🎯 *META DE GERAÇÃO PARA HOJE*\n"
        msg_manha += f"• *Meta Estimada:* `{fmt_br(meta_dia, 2)} kWh` (~R$ {fmt_br(meta_dia*TARIFA_KWH, 2)})\n"
        msg_manha += f"• *Capacidade:* `{fmt_br(POTENCIA_INSTALADA_WP/1000.0, 1)} kWp`\n"
        msg_manha += f"• *Status:* 🟢 Equipamentos ligados e operando\n\n"
        msg_manha += f"🌐 *Painel ao vivo:* {PAINEL_WEB_URL}"
        enviar_telegram(msg_manha)
        return

    if hora_int >= 17 and real_power_val <= 10 and not estado.get("fechamento_enviado", False) and estado.get("dia_ativo", False):
        estado["dia_ativo"] = False
        estado["fechamento_enviado"] = True
        salvar_estado(estado)

        status_meta = f"🟢 `{fmt_br(pct_meta_dia, 1)}% da meta atingida`" if pct_meta_dia >= 100 else f"🟡 `{fmt_br(pct_meta_dia, 1)}% da meta atingida`"

        msg_noite = f"🌙 *FIM DA IRRADIAÇÃO SOLAR* 🌙\n"
        msg_noite += f"📅 `{hora_str}` | Usina em Repouso\n\n"
        msg_noite += f"📊 *BALANÇO DO DIA*\n"
        msg_noite += f"• *Gerado Hoje:* `{today_display}`\n"
        msg_noite += f"• *Meta do Dia:* `{fmt_br(meta_dia, 2)} kWh` ({status_meta})\n"
        if peak_power > 0: msg_noite += f"• *Pico Máximo:* `{fmt_br(peak_power, 0)} W`\n"
        msg_noite += f"• *Mês Atual:* `{fmt_br(month_kwh, 2)} kWh`\n\n"
        msg_noite += f"💰 *FINANCEIRO & AMBIENTAL*\n"
        msg_noite += f"• *Economia Hoje:* `R$ {fmt_br(economia_dia, 2)}`\n"
        msg_noite += f"• *Economia no Mês:* `R$ {fmt_br(economia_mes, 2)}`\n"
        msg_noite += f"• *CO₂ Evitado:* `{fmt_br(co2_kg or (total_kwh*0.9), 2)} kg` (~{fmt_br(arvores_calc, 0)} árvores)\n\n"
        msg_noite += f"🌐 *Painel completo:* {PAINEL_WEB_URL}"
        enviar_telegram(msg_noite)
        return

    # Notificação Periódica (A cada 30 min)
    if estado.get("dia_ativo", False) and not estado.get("fechamento_enviado", False) and (real_power_val > 0 or today_kwh > 0):
        status_icon = "🟢 Online (Gerando)" if real_power_val > 10 else "🟡 Baixa Irradiação"
        pico_str = f" | *Pico:* `{fmt_br(peak_power or real_power_val, 0)} W`"

        msg_padrao = f"☀️ *PAINEL SOLAR HOYMILES* ☀️\n"
        msg_padrao += f"📅 `{hora_str}` | {status_icon}\n\n"
        msg_padrao += f"📊 *GERAÇÃO & RENDIMENTO*\n"
        msg_padrao += f"• *Potência Atual:* `{fmt_br(real_power_val, 1)} W` ({fmt_br(eficiencia, 1)}% da usina)\n"
        msg_padrao += f"• *Hoje:* `{today_display}`{pico_str}\n"
        msg_padrao += f"• *Rendimento Diário (HSP):* `{fmt_br(hsp, 2)} h`\n"
        msg_padrao += f"• *Mês Atual:* `{fmt_br(month_kwh, 2)} kWh`\n"
        msg_padrao += f"• *Total Histórico:* `{fmt_br(total_kwh, 2)} kWh`\n\n"
        msg_padrao += f"💰 *ECONOMIA ESTIMADA*\n"
        msg_padrao += f"• *Hoje:* `R$ {fmt_br(economia_dia, 2)}`\n"
        msg_padrao += f"• *Mês Atual:* `R$ {fmt_br(economia_mes, 2)}`\n"
        msg_padrao += f"• *Total Acumulado:* `R$ {fmt_br(economia_total, 2)}`\n\n"

        if grid_v_num > 0:
            msg_padrao += f"⚡ *REDE ELÉTRICA (CA)*\n"
            msg_padrao += f"• *Tensão:* `{fmt_br(grid_v_num, 1)} V` | *Frequência:* `{fmt_br(grid_f_num, 1)} Hz`\n\n"

        if inversores_msg:
            msg_padrao += f"🔌 *TELEMETRIA DE MICROINVERSORES*\n"
            for m in inversores_msg:
                msg_padrao += m + "\n"
            msg_padrao += "\n"

        msg_padrao += f"🌱 *IMPACTO AMBIENTAL*\n"
        msg_padrao += f"• *CO₂ Evitado:* `{fmt_br(co2_kg or (total_kwh*0.9), 2)} kg` (~{fmt_br(arvores_calc, 0)} árvores)\n\n"
        msg_padrao += f"🌐 *Painel Web:* {PAINEL_WEB_URL}"

        enviar_telegram(msg_padrao)
    else:
        print("Ciclo concluído.")

if __name__ == "__main__":
    main()
