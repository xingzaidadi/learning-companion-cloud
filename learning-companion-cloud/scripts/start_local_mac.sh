#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ -d /opt/homebrew/opt/expat/lib ]]; then
  export DYLD_LIBRARY_PATH="/opt/homebrew/opt/expat/lib:${DYLD_LIBRARY_PATH:-}"
fi

if [[ ! -f .env ]]; then
  cp .env.example .env
fi

if [[ ! -x .venv/bin/python ]]; then
  /opt/homebrew/bin/python3.12 -m venv .venv
fi

.venv/bin/python -m pip install -r requirements.txt
exec .venv/bin/python -m uvicorn backend.app:app --host 127.0.0.1 --port 8000
