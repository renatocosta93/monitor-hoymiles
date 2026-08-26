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

# Link do Painel Web no GitHub Pages (que passará a funcionar):
PAINEL_WEB_URL = "https://renatocosta93.github.io/monitor-hoymiles/"

POTENCIA_INSTALADA_WP = 4500.0  # Capacidade de 4.5 kW conforme seu aplicativo S-Miles
TARIFA_KWH = 1.02              # Tarifa média de energia (R$/kWh)

# Localização: Vargem Grande Paulista - SP
LATITUDE = -23.6028
LONGITUDE = -47.0258

FUSO_BR = timezone(timedelta(hours=-3))

# ==========================================
# FUNÇÕES AUXILIARES DE FORMATAÇÃO E CÁLCULO
# ==========================================
def fmt_br(valor, dec=2):
    """Formata números com padrão brasileiro (vírgula decimal)."""
    try:
        num = float(valor)
        return f"{num:,.{dec}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return "0,00"

def converter_energia(valor):
    """Converte valores de energia em kWh."""
    if valor is None:
        return 0.0
    try:
        num = float(str(valor).replace(",", "."))
        if num > 500:  # Trata entradas em Wh
            return round(num / 1000.0, 3)
        return round(num, 3)
    except Exception:
        return 0.0

def converter_co2(valor):
    """Converte valores de CO2 evitado em kg."""
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
    """Busca chaves em dicionários de forma segura."""
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
    labels_json = json.dumps(dados["chart_labels"], ensure_ascii=False)
    values_json = json.dumps(dados["chart_values"])

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
        }}
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
            background-color: var(--bg);
            color: var(--text-main);
            padding: 20px 12px;
        }}
        .container {{ max-width: 800px; margin: 0 auto; }}
        .header {{ text-align: center; margin-bottom: 24px; }}
        .title {{ font-size: 26px; font-weight: 800; display: flex; align-items: center; justify-content: center; gap: 8px; }}
        .badge {{
            display: inline-block;
            margin-top: 8px;
            padding: 4px 14px;
            border-radius: 999px;
            font-size: 13px;
            font-weight: 700;
            background: rgba(16, 185, 129, 0.15);
            color: var(--solar-green);
            border: 1px solid rgba(16, 185, 129, 0.3);
        }}
        .location {{ color: var(--text-muted); font-size: 13px; margin-top: 6px; }}
        
        .card {{
            background: var(--card-bg);
            border: 1px solid var(--card-border);
            border-radius: 18px;
            padding: 20px;
            margin-bottom: 16px;
            box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.3);
        }}
        .power-card {{
            text-align: center;
            background: linear-gradient(180deg, #1e293b 0%, #0f172a 100%);
            border: 1px solid rgba(245, 158, 11, 0.3);
        }}
        .power-val {{
            font-size: 48px;
            font-weight: 900;
            color: var(--solar-amber);
            line-height: 1.1;
            margin: 10px 0;
        }}
        .power-sub {{ color: var(--text-muted); font-size: 14px; }}
        
        .progress-box {{ margin-top: 18px; }}
        .progress-labels {{ display: flex; justify-content: space-between; font-size: 13px; color: var(--text-muted); margin-bottom: 6px; }}
        .progress-bar {{ background: #334155; height: 10px; border-radius: 6px; overflow: hidden; }}
        .progress-fill {{ background: var(--solar-amber); height: 100%; border-radius: 6px; }}

        .grid-cards {{ display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin-bottom: 16px; }}
        .grid-3 {{ display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 12px; }}
        
        .stat-label {{ font-size: 12px; color: var(--text-muted); text-transform: uppercase; font-weight: 700; }}
        .stat-val {{ font-size: 22px; font-weight: 800; margin: 4px 0; color: var(--text-main); }}
        .stat-sub {{ font-size: 13px; color: var(--solar-green); font-weight: 600; }}

        .chart-box {{ margin-top: 10px; height: 220px; position: relative; }}
        
        .inverter-item {{
            background: #0f172a;
            border: 1px solid #334155;
            border-radius: 12px;
            padding: 14px;
            margin-top: 10px;
        }}
        .inv-head {{ display: flex; justify-content: space-between; font-weight: 700; font-size: 14px; margin-bottom: 8px; }}
        .inv-pv {{ font-size: 12px; color: var(--text-muted); margin-left: 12px; font-family: monospace; }}
    </style>
</head>
<body>
    <div class="container">
        <header class="header">
            <h1 class="title">☀️ Painel Solar Hoymiles</h1>
            <span class="badge">{dados['status_str']}</span>
            <p class="location">📍 Vargem Grande Paulista - SP | Atualizado às {dados['hora_atual']}</p>
        </header>

        <div class="card power-card">
            <div class="stat-label">Potência Instantânea de Geração</div>
            <div class="power-val">{dados['real_power']} <span style="font-size: 24px;">W</span></div>
            <div class="power-sub">{dados['eficiencia']}% da capacidade total ({int(POTENCIA_INSTALADA_WP)} Wp)</div>
            
            <div class="progress-box">
                <div class="progress-labels">
                    <span>Hoje: {dados['today_str']}</span>
                    <span><b>{dados['pct_meta']}%</b> da meta ({dados['meta_kwh']} kWh)</span>
                </div>
                <div class="progress-bar">
                    <div class="progress-fill" style="width: {min(dados['pct_meta_num'], 100)}%;"></div>
                </div>
            </div>
        </div>

        <div class="card">
            <div class="stat-label">Curva de Produção por Horário (Hoje)</div>
            <div class="chart-box">
                <canvas id="solarChart"></canvas>
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
                <div class="stat-val">{dados['month_kwh']} <span style="font-size: 15px;">kWh</span></div>
                <div class="stat-sub">Economia: R$ {dados['economia_mes']}</div>
            </div>
        </div>

        <div class="grid-3">
            <div class="card">
                <div class="stat-label">Total Histórico</div>
                <div class="stat-val" style="font-size: 18px;">{dados['total_kwh']} <span style="font-size: 12px;">kWh</span></div>
                <div class="stat-sub" style="font-size: 12px;">R$ {dados['economia_total']}</div>
            </div>
            <div class="card">
                <div class="stat-label">Pico do Dia</div>
                <div class="stat-val" style="font-size: 18px;">{dados['peak_power']} <span style="font-size: 12px;">W</span></div>
                <div style="font-size: 12px; color: var(--text-muted);">{dados['hsp']} HSP</div>
            </div>
            <div class="card">
                <div class="stat-label">CO₂ Evitado</div>
                <div class="stat-val" style="font-size: 18px;">{dados['co2_kg']} <span style="font-size: 12px;">kg</span></div>
                <div style="font-size: 12px; color: var(--solar-green);">~{dados['arvores']} árvores</div>
            </div>
        </div>

        <div class="card">
            <div class="stat-label" style="margin-bottom: 8px;">Telemetria da Rede Elétrica & Microinversores</div>
            <p style="font-size: 14px; margin-bottom: 12px;">
                Tensão da Rede: <b>{dados['grid_v']} V</b> | Frequência: <b>{dados['grid_f']} Hz</b>
            </p>
            {dados['inversores_html']}
        </div>
    </div>

    <script>
        const ctx = document.getElementById('solarChart').getContext('2d');
        const labels = {labels_json};
        const values = {values_json};

        new Chart(ctx, {{
            type: 'line',
            data: {{
                labels: labels,
                datasets: [{{
                    label: 'Potência Gerada (W)',
                    data: values,
                    borderColor: '#f59e0b',
                    backgroundColor: 'rgba(245, 158, 11, 0.15)',
                    borderWidth: 2.5,
                    fill: true,
                    tension: 0.35,
                    pointRadius: 2,
                    pointHoverRadius: 5
                }}]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                plugins: {{
                    legend: {{ display: false }},
                    tooltip: {{
                        callbacks: {{
                            label: function(context) {{
                                return context.raw + ' W';
                            }}
                        }}
                    }}
                }},
                scales: {{
                    x: {{
                        grid: {{ color: 'rgba(255, 255, 255, 0.05)' }},
                        ticks: {{ color: '#94a3b8', font: {{ size: 10 }}, maxTicksLimit: 12 }}
                    }},
                    y: {{
                        grid: {{ color: 'rgba(255, 255, 255, 0.05)' }},
                        ticks: {{ color: '#94a3b8', font: {{ size: 10 }} }},
                        suggestedMin: 0
                    }}
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
    hora_str = agora_br.strftime("%d/%m/%Y - %H:%M")

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

    # Destrava automaticamente no período diurno
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

            # Captura visual de segurança do DOM
            js_dom = """
            () => {
                let text = document.body.innerText || '';
                return { all_text: text };
            }
            """
            scraped_dom = page.evaluate(js_dom)

            # Requisições autenticadas da sessão ativa
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

    # Processamento e Extração dos Dados
    real_power_val = 0.0
    today_eq_raw = None
    month_eq_raw = None
    total_eq_raw = None
    peak_power = 0.0
    co2_raw = None
    grid_v_num = 0.0
    grid_f_num = 60.0
    inversores_dict = {}
    chart_points = []

    def varrer(obj):
        nonlocal real_power_val, today_eq_raw, month_eq_raw, total_eq_raw, peak_power, co2_raw, grid_v_num, grid_f_num, chart_points
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

            c_list = extrair_campo(obj, ["chart_list", "power_list", "points", "detail"])
            if c_list and isinstance(c_list, list) and len(c_list) > len(chart_points):
                chart_points = c_list

            sn = extrair_campo(obj, ["sn", "mi_sn", "inverter_sn"])
            if sn and str(sn).strip().isdigit() and len(str(sn).strip()) >= 8:
                inversores_dict[str(sn)] = obj

            for v in obj.values(): varrer(v)
        elif isinstance(obj, list):
            for i in obj: varrer(i)

    for item in captured_data: varrer(item)

    # Leitura de contingência pelo texto renderizado na tela
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

    meta_dia = estado.get("meta_kwh", 18.0)
    pct_meta = round((today_kwh / meta_dia) * 100, 1) if meta_dia > 0 else 0
    economia_dia = round(today_kwh * TARIFA_KWH, 2)
    economia_mes = round(month_kwh * TARIFA_KWH, 2)
    economia_total = round(total_kwh * TARIFA_KWH, 2)
    eficiencia = round((real_power_val / POTENCIA_INSTALADA_WP) * 100, 1) if POTENCIA_INSTALADA_WP > 0 else 0
    hsp = round(today_kwh / (POTENCIA_INSTALADA_WP / 1000.0), 2) if POTENCIA_INSTALADA_WP > 0 else 0
    arvores_calc = round(co2_kg / 20.0, 1) if co2_kg > 0 else round(total_kwh * 0.05, 1)

    # Formatação especial para exibição em Wh / kWh
    if today_kwh < 1.0 and today_kwh > 0:
        today_display = f"{int(round(today_kwh * 1000))} Wh ({fmt_br(today_kwh, 2)} kWh)"
    else:
        today_display = f"{fmt_br(today_kwh, 2)} kWh"

    print(f"📊 LEITURA REAL: Potência={real_power_val}W | Hoje={today_display} | Mês={month_kwh}kWh | Total={total_kwh}kWh")

    # Gráfico Horário
    chart_labels = []
    chart_values = []
    if chart_points:
        for pt in chart_points:
            if isinstance(pt, dict):
                t_str = str(pt.get("time") or pt.get("date") or "")
                v_num = float(str(pt.get("val") or pt.get("power") or 0).replace(",", "."))
                if t_str:
                    hora_curta = t_str.split(" ")[-1][:5]
                    chart_labels.append(hora_curta)
                    chart_values.append(round(v_num, 1))
                    if v_num > peak_power: peak_power = v_num
    
    if not chart_labels:
        chart_labels = ["06:00", "07:00", "08:00", "10:00", "12:00", "14:00", "16:00", "18:00"]
        chart_values = [0, round(real_power_val * 0.5, 1), round(real_power_val, 1), round(real_power_val * 1.5, 1), round(peak_power or real_power_val * 2, 1), round(real_power_val * 1.2, 1), round(real_power_val * 0.4, 1), 0]

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
            <div style="font-size: 13px; color: var(--text-muted); margin-bottom: 6px;">
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

    status_str = "Online (Gerando)" if real_power_val > 10 else "Baixa Irradiação / Repouso"
    gerar_painel_html({
        "status_str": status_str,
        "hora_atual": hora_str,
        "real_power": fmt_br(real_power_val, 1),
        "eficiencia": fmt_br(eficiencia, 1),
        "today_str": today_display,
        "meta_kwh": fmt_br(meta_dia, 2),
        "pct_meta": fmt_br(pct_meta, 1),
        "pct_meta_num": pct_meta,
        "month_kwh": fmt_br(month_kwh, 2),
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
        "chart_labels": chart_labels,
        "chart_values": chart_values,
        "inversores_html": inv_html or "<p style='color: var(--text-muted); font-size: 13px;'>Microinversores sincronizados via DTU.</p>"
    })

    # ==========================================
    # 3. ATIVAÇÃO MATINAL INCONDICIONAL (05h - 11h)
    # ==========================================
    if (5 <= hora_int <= 11) and not estado.get("dia_ativo", False):
        estado["dia_ativo"] = True
        estado["fechamento_enviado"] = False
        salvar_estado(estado)

        meta_dia = estado.get("meta_kwh", 18.0)
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

    # ==========================================
    # 4. ENCERRAMENTO DO DIA (Após 17h00)
    # ==========================================
    if hora_int >= 17 and real_power_val <= 10 and not estado.get("fechamento_enviado", False) and estado.get("dia_ativo", False):
        estado["dia_ativo"] = False
        estado["fechamento_enviado"] = True
        salvar_estado(estado)

        status_meta = f"🟢 `{fmt_br(pct_meta, 1)}% da meta atingida`" if pct_meta >= 100 else f"🟡 `{fmt_br(pct_meta, 1)}% da meta atingida`"

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

    # ==========================================
    # 5. ALERTA DE ANOMALIAS
    # ==========================================
    anomalias = []
    if (8 <= hora_int <= 16) and real_power_val < 5 and estado.get("dia_ativo", False):
        anomalias.append("Usina sem geração em horário de sol pleno.")
    if grid_v_num > 245.0:
        anomalias.append(f"Sobretensão na Rede CA ({fmt_br(grid_v_num, 1)}V > 245V).")
    elif 0 < grid_v_num < 200.0:
        anomalias.append(f"Subtensão na Rede CA ({fmt_br(grid_v_num, 1)}V < 200V).")

    if anomalias and estado.get("ultimo_alerta") != anomalias[0]:
        estado["ultimo_alerta"] = anomalias[0]
        salvar_estado(estado)

        msg_alerta = f"🚨 *ALERTA DE ANOMALIA SOLAR* 🚨\n"
        msg_alerta += f"📅 `{hora_str}`\n\n"
        msg_alerta += f"⚠️ *EVENTO DETECTADO:*\n"
        for a in anomalias: msg_alerta += f"• {a}\n"
        msg_alerta += f"\n📊 *Potência:* `{fmt_br(real_power_val, 1)} W` | *Rede:* `{fmt_br(grid_v_num, 1)} V`\n\n"
        msg_alerta += f"🌐 *Ver detalhes:* {PAINEL_WEB_URL}"
        enviar_telegram(msg_alerta)

    # ==========================================
    # 6. NOTIFICAÇÃO PADRÃO DE PRODUÇÃO (A cada 30 min) — EXIGE `dia_ativo` = True E GERAÇÃO REAL
    # ==========================================
    if estado.get("dia_ativo", False) and not estado.get("fechamento_enviado", False) and (real_power_val > 0 or today_kwh > 0):
        status_icon = "🟢 Online (Gerando)" if real_power_val > 10 else "🟡 Baixa Irradiação"
        pico_str = f" | *Pico:* `{fmt_br(peak_power or real_power_val, 0)} W`"

        msg_padrao = f"☀️ *USINA MENDES* ☀️\n"
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
