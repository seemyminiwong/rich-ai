#!/bin/sh
# Which version is actually RUNNING here?
#
# "git log" alone lies by omission: after git reset the folder holds new code,
# but the containers keep serving whatever they were built from. So compare the
# repo commit time against the api image build time and give a verdict.
set -e
cd "$(dirname "$0")/.."

echo "=== Репозиторій ==="
git log -1 --format='коміт    %h  %s'
git log -1 --format='зроблено %ci'
COMMIT_TS=$(git log -1 --format=%ct)

echo ""
echo "=== Запущені контейнери ==="
API_IMAGE=$(docker compose images api 2>/dev/null | awk 'NR==2{print $2":"$3}')
IMG_CREATED=$(docker image inspect --format '{{.Created}}' "$API_IMAGE" 2>/dev/null || echo '')
if [ -z "$IMG_CREATED" ]; then
  echo "образ api не знайдено — docker compose ps:"
  docker compose ps
  exit 1
fi
echo "образ api зібрано: $IMG_CREATED"
IMG_TS=$(date -d "$IMG_CREATED" +%s 2>/dev/null || echo 0)

echo ""
echo "=== Живі версії ==="
printf 'health:      '; curl -sf --max-time 5 http://127.0.0.1:8000/health || echo 'API не відповідає'
echo ""
printf 'кеш-бастер:  '; grep -o 'app.js?b=[0-9]*' apps/web/index.html | head -1

echo ""
if [ "$IMG_TS" -ge "$COMMIT_TS" ]; then
  echo "ВЕРДИКТ: образ зібрано ПІСЛЯ останнього коміту — працює актуальний код."
else
  echo "ВЕРДИКТ: образ СТАРШИЙ за останній коміт — контейнери працюють на старому коді."
  echo "Перезберіть: docker compose up -d --force-recreate --build"
fi
