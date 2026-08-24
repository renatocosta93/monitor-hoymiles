
name: Monitor Hoymiles 30min

on:
  schedule:
    - cron: '*/30 * * * *'
  workflow_dispatch:

jobs:
  run-monitor:
    runs-on: ubuntu-latest
    steps:
      - name: Baixar código
        uses: actions/checkout@v4

      - name: Configurar Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.10'

      - name: Instalar Playwright e Navegador
        run: |
          pip install playwright requests
          playwright install --with-deps chromium

      - name: Executar Script
        run: python monitor_hoymiles.py

