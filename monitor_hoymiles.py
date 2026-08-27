name: Monitor Hoymiles 30min

on:
  schedule:
    # Executa a cada 30 min (minutos :05 e :35) das 05h às 20h30 BRT (08h às 23h30 UTC)
    - cron: '5,35 8-23 * * *'
  workflow_dispatch:

permissions:
  contents: write

jobs:
  run-monitor:
    runs-on: ubuntu-latest
    steps:
      - name: Baixar código
        uses: actions/checkout@v4
        with:
          fetch-depth: 1

      - name: Configurar Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.10'

      - name: Instalar Dependências e Navegador
        run: |
          pip install playwright requests
          playwright install --with-deps chromium

      - name: Executar Monitoramento
        run: python monitor_hoymiles.py

      - name: Publicar Painel Web e Estado
        run: |
          git config --global user.name "GitHub Actions Bot"
          git config --global user.email "actions@github.com"
          git add index.html state.json || true
          git diff --quiet && git diff --staged --quiet || (git commit -m "Auto-update Solar Web Dashboard [skip ci]" && git push)
