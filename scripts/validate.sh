#!/usr/bin/env sh
set -eu
python3 -m compileall -q apps/api/app
node --check apps/web/app.js
python3 - <<'PY'
import json
from pathlib import Path
import yaml
json.loads(Path('config/artline-palette.json').read_text())
yaml.safe_load(Path('docker-compose.yml').read_text())
print('Validation OK')
PY
