#!/usr/bin/env sh
set -eu
python3 -m compileall -q apps/api/app
NODE_BIN="${NODE_BIN:-node}"
if command -v "$NODE_BIN" >/dev/null 2>&1; then
  "$NODE_BIN" --check apps/web/app.js
else
  echo "Node.js not found; JavaScript syntax check skipped"
fi
python3 scripts/smoke_v11_2.py
python3 - <<'PY'
import json
from pathlib import Path
json.loads(Path('config/artline-palette.json').read_text())
print('Palette JSON OK')
PY
if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  docker compose config >/dev/null
  echo "Docker Compose config OK"
else
  echo "Docker Compose unavailable; config validation skipped"
fi
echo "Validation OK"
