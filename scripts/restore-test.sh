#!/bin/sh
# Restore drill: prove the newest dump actually restores.
#
# An untested backup is a hope, not a backup. This spins a throwaway Postgres,
# restores the latest dump into it, counts the tables that matter and throws the
# container away. It never touches the production database.
set -e
cd "$(dirname "$0")/.."

DUMP=$(ls -1t backups/richstudio-*.dump 2>/dev/null | head -1)
if [ -z "$DUMP" ]; then
  echo "Немає жодного дампа в ./backups — бекап ще не відпрацював або не змігрував зі старого тому."
  exit 1
fi
echo "Перевіряю: $DUMP ($(du -h "$DUMP" | cut -f1))"

NAME=richstudio-restore-test
docker rm -f "$NAME" >/dev/null 2>&1 || true
docker run -d --name "$NAME" -e POSTGRES_PASSWORD=drill -e POSTGRES_DB=drill postgres:16-alpine >/dev/null

echo "Чекаю на тестовий Postgres..."
for i in $(seq 1 30); do
  docker exec "$NAME" pg_isready -U postgres -d drill >/dev/null 2>&1 && break
  sleep 1
done

docker cp "$DUMP" "$NAME:/tmp/drill.dump"
docker exec "$NAME" pg_restore -U postgres -d drill --no-owner --no-privileges /tmp/drill.dump

echo ""
echo "=== Що всередині відновленої бази ==="
docker exec "$NAME" psql -U postgres -d drill -t -A -F' | ' -c "
  SELECT 'проєкти', count(*) FROM richstudio_v11_2.projects
  UNION ALL SELECT 'артефакти (HTML)', count(*) FROM richstudio_v11_2.artifacts
  UNION ALL SELECT 'стилі', count(*) FROM richstudio_v11_2.styles
  UNION ALL SELECT 'користувачі', count(*) FROM richstudio_v11_2.users;"

docker rm -f "$NAME" >/dev/null
echo ""
echo "ВЕРДИКТ: дамп відновлюється. Тестовий контейнер прибрано, прод не торкався."
