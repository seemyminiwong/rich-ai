#!/bin/sh
# Which version is actually RUNNING here?
#
# Comparing an image against the latest commit gives false alarms: a frontend-only
# commit leaves every api layer cached, so Docker reuses the old api image (old
# Created timestamp) and that is CORRECT. Compare each image against the last
# commit that touched the files it is built from instead.
set -e
cd "$(dirname "$0")/.."

echo "=== Репозиторій ==="
git log -1 --format='коміт    %h  %s'
git log -1 --format='зроблено %ci'

check_service() {
  SERVICE=$1
  shift
  SRC_TS=$(git log -1 --format=%ct -- "$@" 2>/dev/null || echo 0)
  SRC_AT=$(git log -1 --format='%h %ci' -- "$@" 2>/dev/null || echo '?')
  IMAGE=$(docker compose images "$SERVICE" 2>/dev/null | awk 'NR==2{print $2":"$3}')
  CREATED=$(docker image inspect --format '{{.Created}}' "$IMAGE" 2>/dev/null || echo '')
  if [ -z "$CREATED" ]; then
    echo "$SERVICE: образ не знайдено"
    STALE=1
    return
  fi
  IMG_TS=$(date -d "$CREATED" +%s 2>/dev/null || echo 0)
  if [ "$IMG_TS" -ge "$SRC_TS" ]; then
    echo "$SERVICE: OK (останні зміни його файлів: $SRC_AT)"
  else
    echo "$SERVICE: ЗАСТАРІВ — образ зібрано $CREATED, а його файли змінено $SRC_AT"
    STALE=1
  fi
}

echo ""
echo "=== Сервіси ==="
STALE=0
check_service api apps/api
check_service worker apps/api
check_service web apps/web

echo ""
echo "=== Живі версії ==="
printf 'health:      '; curl -sf --max-time 5 http://127.0.0.1:8000/health || echo 'API не відповідає'
echo ""
printf 'кеш-бастер:  '; grep -o 'app.js?b=[0-9]*' apps/web/index.html | head -1

echo ""
if [ "$STALE" -eq 0 ]; then
  echo "ВЕРДИКТ: усі сервіси зібрано з актуального коду."
else
  echo "ВЕРДИКТ: є застарілі сервіси — перезберіть: docker compose up -d --force-recreate --build"
fi
