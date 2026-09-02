#!/usr/bin/env bash
set -euo pipefail

APP_HOST="${APP_HOST:-127.0.0.1}"
APP_PORT="${APP_PORT:-8010}"
VENV_DIR="${VENV_DIR:-.venv}"

cd "$(dirname "$0")"

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 nao encontrado. Instale o Python 3.11 ou superior."
  exit 1
fi

if [ ! -d "$VENV_DIR" ]; then
  echo "Criando ambiente virtual em $VENV_DIR..."
  python3 -m venv "$VENV_DIR"
fi

source "$VENV_DIR/bin/activate"

echo "Atualizando dependencias..."
python -m pip install --upgrade pip
python -m pip install -e .

echo "Garantindo navegador Chromium do Playwright..."
python -m playwright install chromium

echo
echo "HUB RPA iniciado em: http://$APP_HOST:$APP_PORT"
echo "Documentacao da API: http://$APP_HOST:$APP_PORT/docs"
echo

python -m uvicorn apps.api.rpa_hub_api.main:app --reload --host "$APP_HOST" --port "$APP_PORT"
