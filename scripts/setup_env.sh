#!/usr/bin/env bash
# One-click setup for walkie: venv, pip deps, ollama, model pull.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "==> Creating local config from examples"
mkdir -p config
[ -f config/settings.yaml ] || cp config/settings.example.yaml config/settings.yaml

echo "==> Creating venv"
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e ".[dev]"

echo "==> Checking Ollama"
if ! command -v ollama >/dev/null 2>&1; then
  echo "Ollama not found. Install from https://ollama.com/download then re-run."
  exit 1
fi
ollama pull llama3.2:3b

echo "==> Fetching OSM region extract"
if ! python -m walkie region; then
  echo "Region fetch failed (offline or detection issue). Run later: make region"
fi

echo "==> Done. Activate with: source .venv/bin/activate"
