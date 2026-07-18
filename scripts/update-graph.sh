#!/bin/sh
# Скопіювати свіжий Graphify-граф туди, звідки його забирає образ API.
set -e
cd "$(dirname "$0")/.."
if [ ! -f graphify-out/graph.html ]; then
  echo "Немає graphify-out/graph.html — спершу запустіть /graphify . у Claude Code"
  exit 1
fi
cp graphify-out/graph.html apps/api/graph/graph.html
echo "OK: apps/api/graph/graph.html оновлено ($(du -h apps/api/graph/graph.html | cut -f1))."
echo "Далі: git add -A && git commit -m 'graph: refresh codebase map' && git push, потім деплой."
