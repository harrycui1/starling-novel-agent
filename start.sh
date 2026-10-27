#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  uv venv --python 3.11 .venv
  uv pip install --python .venv/bin/python -e '.[dev]'
fi
if [ ! -d frontend/node_modules ]; then
  npm --prefix frontend ci --no-audit --no-fund
fi
npm --prefix frontend run build
exec .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8767 --timeout-graceful-shutdown 3
