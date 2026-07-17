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

cleanup() { docker rm -f "$NAME" >/dev/null 2>&1 || true; }
trap cleanup EXIT

echo "Чекаю на тестовий Postgres..."
# pg_isready тут НЕ годиться: під час першого запуску образ postgres піднімає
# ТИМЧАСОВИЙ сервер для init-скриптів і потім гасить його — pg_isready встигає
# відповісти «ок», а pg_restore влучає у «the database system is shutting down»
# (перше навчання з відновлення впало саме так). Тимчасовий сервер не живе двох
# перевірок поспіль, тому чекаємо на два успішні SELECT 1 з паузою між ними.
ok=0
for i in $(seq 1 60); do
  if docker exec "$NAME" psql -U postgres -d drill -c 'SELECT 1' >/dev/null 2>&1; then
    ok=$((ok+1))
    [ "$ok" -ge 2 ] && break
  else
    ok=0
  fi
  sleep 2
done
if [ "$ok" -lt 2 ]; then
  echo "Postgres так і не піднявся. Останні логи контейнера:"
  docker logs --tail 15 "$NAME"
  exit 1
fi

docker cp "$DUMP" "$NAME:/tmp/drill.dump"
docker exec "$NAME" pg_restore -U postgres -d drill --no-owner --no-privileges /tmp/drill.dump

echo ""
echo "=== Що всередині відновленої бази ==="
docker exec "$NAME" psql -U postgres -d drill -t -A -F' | ' -c "
  SELECT 'проєкти', count(*) FROM richstudio_v11_2.projects
  UNION ALL SELECT 'артефакти (HTML)', count(*) FROM richstudio_v11_2.artifacts
  UNION ALL SELECT 'стилі', count(*) FROM richstudio_v11_2.styles
  UNION ALL SELECT 'користувачі', count(*) FROM richstudio_v11_2.users;"

echo ""
echo "ВЕРДИКТ: дамп відновлюється. Тестовий контейнер прибрано, прод не торкався."
