#!/bin/sh
set -eu
cd "$(dirname "$0")"
if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env from .env.example. Edit passwords and OPENAI_API_KEY, then run this script again."
  exit 1
fi
if grep -qE '^(POSTGRES_PASSWORD=change-this-db-password|JWT_SECRET=replace-with-a-long-random-secret|ADMIN_PASSWORD=change-this-admin-password)$' .env; then
  echo "Refusing to deploy with placeholder passwords/secrets. Edit .env first."
  exit 1
fi
sudo docker compose config >/dev/null
sudo docker compose down --remove-orphans
sudo docker compose build --no-cache
sudo docker compose up -d
printf 'Waiting for API health'
i=0
while [ "$i" -lt 60 ]; do
  if curl -fsS http://127.0.0.1:8000/health >/dev/null 2>&1; then
    echo
    sudo docker compose ps
    echo "Rich Studio is ready: http://$(hostname -I | awk '{print $1}'):3000"
    exit 0
  fi
  printf '.'
  i=$((i+1))
  sleep 2
done
echo
sudo docker compose ps
sudo docker compose logs api --tail=100
exit 1
