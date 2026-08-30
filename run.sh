#!/usr/bin/env bash
# Avvio della piattaforma LogisticMaster.
set -euo pipefail
cd "$(dirname "$0")"
python3 -m pip install --quiet -r requirements.txt
exec python3 -m uvicorn app.main:app --host "${HOST:-0.0.0.0}" --port "${PORT:-8000}" "$@"
