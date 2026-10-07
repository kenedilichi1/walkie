#!/usr/bin/env bash
# One-click setup for walkie: venv, pip deps, ollama, model pull.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "==> Creating local config from examples"
mkdir -p config
[ -f config/settings.yaml ] || cp config/settings.example.yaml config/settings.yaml
[ -f config/prefs.json ] || cp config/prefs.example.json config/prefs.json

echo "==> Creating venv"
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
pip install -e .

echo "==> Checking Ollama"
if ! command -v ollama >/dev/null 2>&1; then
  echo "Ollama not found. Install from https://ollama.com/download then re-run."
  exit 1
fi
ollama pull llama3.2 || ollama pull phi3.5-mini

echo "==> Done. Activate with: source .venv/bin/activate"
