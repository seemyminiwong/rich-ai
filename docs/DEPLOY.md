# Deployment & operations runbook

ARTLINE Rich Studio. Repository: `github.com/seemyminiwong/rich-ai`.
Production host: TrueNAS, project directory `/mnt/Data/Apps/rich-studio/rich-ai`,
docker compose project name `rich-ai`.

---

## 1. Versioning

Single source of truth: `apps/api/app/version.py` (`__version__`). The health
endpoint and Docker image tags derive from it. On release, bump it and keep the
`?v=` query in `apps/web/index.html` in sync, then tag the commit:

```bash
git tag v12.0
git push origin v12.0
```

---

## 2. Develop → GitHub (on your Mac)

```bash
cd ~/Documents/Random/artline-rich-studio-v11.8
git add .
git commit -m "…"
git push
```

Every push to `main` runs CI (`.github/workflows/ci.yml`): Python compile,
JS syntax check, smoke checks, pytest. On success it builds and pushes images to
GHCR:

- `ghcr.io/seemyminiwong/rich-ai-api:latest` (also `:<version>` and `:<sha>`)
- `ghcr.io/seemyminiwong/rich-ai-web:latest`

The `worker` service reuses the `rich-ai-api` image.

---

## 3. Deploy on TrueNAS — pull prebuilt images (recommended)

No build on the NAS, no git needed. One-time: create a GHCR read token
(github.com → Settings → Developer settings → Personal access tokens → classic,
scope `read:packages`) and log in on the host (as root):

```bash
echo 'YOUR_READ_PACKAGES_TOKEN' | docker login ghcr.io -u seemyminiwong --password-stdin
```

Then, for every release (as root — `sudo -i` first):

```bash
cd /mnt/Data/Apps/rich-studio/rich-ai
export IMAGE_TAG=latest
docker compose -f docker-compose.yml -f docker-compose.registry.yml pull
docker compose -f docker-compose.yml -f docker-compose.registry.yml up -d
curl http://127.0.0.1:8000/health
```

Pin a specific version instead of `latest` with `export IMAGE_TAG=12.0`.

You still need the repository checkout on the host for the compose files and
`.env`; update them with `git pull` (the code itself now comes from the images).

## 3b. Deploy by building on the host (legacy fallback)

If GHCR is unavailable, the old path still works (as root):

```bash
cd /mnt/Data/Apps/rich-studio/rich-ai
git fetch origin && git reset --hard origin/main
docker compose up -d --force-recreate --build
```

---

## 4. Rollback

```bash
export IMAGE_TAG=11.10        # previous known-good version
docker compose -f docker-compose.yml -f docker-compose.registry.yml up -d
curl http://127.0.0.1:8000/health
```

Data (Postgres, media) lives in named volumes `rich-ai_postgres_data` and
`rich-ai_media_data` and is untouched by image changes.

---

## 5. Backup & restore

**Automatic:** the `backup` compose service dumps the database daily (custom
format) into the `rich-ai_backup_data` volume and prunes dumps older than
`BACKUP_KEEP_DAYS` (default 14). List and restore:

```bash
docker compose exec backup ls -lh /backups
docker compose exec backup sh -c 'pg_restore --clean --if-exists -d "$PGDATABASE" /backups/richstudio-YYYY-MM-DD-HHMM.dump'
```

Manual one-off dump:

```bash
docker compose exec -T postgres pg_dump -U richstudio richstudio > backup-$(date +%F).sql
```

Media (generated images) lives in the `rich-ai_media_data` volume — snapshot it
with the rest of the `Data` pool via TrueNAS snapshots.

## 5b. Failure alerts & watchdog

The worker runs a beat schedule: every 5 minutes a watchdog fails projects stuck
in `processing`/`queued` longer than `STUCK_PROJECT_MINUTES` (default 45) and
posts an alert. Alerts also fire on every project error.

Configure any of these in `.env` (empty = disabled):

```env
TELEGRAM_BOT_TOKEN=...   # @BotFather token
TELEGRAM_CHAT_ID=...     # your chat/channel id
ALERT_WEBHOOK_URL=...    # any endpoint accepting JSON POST {"text": ...}
```

---

## 6. Database migrations (Alembic) — opt-in

The app currently manages its schema with `create_all` plus idempotent
`ALTER TABLE ... IF NOT EXISTS` in `app/db.py`. Alembic is scaffolded under
`apps/api/alembic/` and ready to become the schema authority. Enable it once,
carefully, after testing on a database copy:

1. Add to `apps/api/Dockerfile` before `EXPOSE`:

   ```dockerfile
   COPY alembic.ini .
   COPY alembic ./alembic
   ```

2. Rebuild the API image (via CI).

3. Mark the **existing** production DB as already at baseline (no data change):

   ```bash
   docker compose exec api alembic stamp head
   ```

4. From then on, generate and apply migrations for every schema change:

   ```bash
   docker compose exec api alembic revision --autogenerate -m "describe change"
   docker compose exec api alembic upgrade head
   ```

Test steps 3–4 against a `pg_dump` restore in a scratch database before running
them on production.

## HTTPS (Caddy + Let's Encrypt)

Профіль `tls` вимкнено за замовчуванням — без домену все працює як раніше, через порт 3000 у локальній мережі.

Передумови:

1. Домен (наприклад `studio.example.com`) з A-записом на публічну IP-адресу сервера.
2. Порти **80 і 443** прокинуті з роутера на сервер. Порт 80 обов'язковий — на нього приходить ACME-виклик Let's Encrypt.
3. На TrueNAS SCALE веб-інтерфейс сам слухає 80/443. Звільніть їх: **System Settings → General → GUI**, змініть Web Interface HTTP/HTTPS Port на 880/8443, збережіть.

Увімкнення:

```bash
cd /mnt/Data/Apps/rich-studio/rich-ai
echo 'PUBLIC_DOMAIN=studio.example.com' >> .env
docker compose --profile tls up -d
docker compose logs -f caddy
```

У лозі Caddy має з'явитися `certificate obtained successfully`. Далі студія доступна на `https://studio.example.com`, сертифікат оновлюється автоматично.

Вимкнути HTTPS: `docker compose --profile tls down caddy` (решта сервісів не зачіпається).

Зауваження:

- Заголовки безпеки й кеш живуть у nginx; Caddy додає лише HSTS (тиждень для початку — підніміть до року, коли HTTPS постабілізується).
- `PUBLIC_DOMAIN` порожній → профіль tls відмовиться стартувати з зрозумілою помилкою; сервіси без профілю не постраждають.
- Порт 3000 лишається як локальний вхід. Якщо він не потрібен зовні, не прокидайте його з роутера.

## Міграції БД (Alembic)

Міграції застосовуються автоматично під час старту API — окремих команд при деплої немає.

- Свіжа база: створюється повна схема (`0001_baseline`), далі всі ревізії.
- База, що існувала до Alembic: при першому старті вона позначається як `0001_baseline`, і застосовуються наступні ревізії. Вони ідемпотентні, тож база, яка вже отримала ці зміни старим шляхом, оновлюється без конфліктів.
- Нову зміну схеми додавайте новою ревізією в `apps/api/alembic/versions/`, ланцюжок має лишатися лінійним.

Ручний запуск (з контейнера api): `docker compose exec api alembic upgrade head`, поточна ревізія — `docker compose exec api alembic current`.

## Бекапи: що і куди

Контейнер `backup` щодоби складає в `./backups` (тобто `/mnt/Data/Apps/rich-studio/rich-ai/backups` на пулі):

- `richstudio-*.dump` — БД (pg_dump -Fc), кожен дамп одразу перевіряється `pg_restore --list`; битий дамп видаляється і летить алерт у Telegram, а не зберігається;
- `media-*.tar.gz` — усі згенеровані зображення. Без них відновлена база посилалась би на неіснуючі файли.

Обидва типи чистяться після `BACKUP_KEEP_DAYS` (типово 14).

**Обов'язковий крок, який робиться руками в TrueNAS UI:** бекап на тому ж диску переживає помилки, але не диск. Offsite-копія, покроково (TrueNAS SCALE, ~10 хвилин):

1. Заведіть бакет у Backblaze B2 (найдешевше) або будь-якому S3: `artline-rich-backups`, приватний. Створіть application key лише на цей бакет.
2. TrueNAS → **Credentials → Backup Credentials → Cloud Credentials → Add**: тип Backblaze B2 (або Amazon S3), вставте keyID/applicationKey, Verify Credential.
3. **Data Protection → Cloud Sync Tasks → Add**:
   - Direction **Push**, Transfer Mode **Copy** (не Sync: випадкове локальне видалення не зітре offsite-копію);
   - Source `/mnt/Data/Apps/rich-studio/rich-ai/backups`, Target — бакет;
   - Schedule: щодня, на годину пізніше за контейнер `backup` (щоб забирати вже свіжий дамп);
   - **Remote Encryption: увімкнути** і зберегти парольну фразу в менеджері паролів. Старі дампи, зроблені до Fernet-шифрування ключів, містять ключі провайдерів відкритим текстом — у хмару вони мають їхати лише зашифрованими.
4. Кнопка **Dry Run** — перелік файлів без передачі; потім **Run Now** і перевірте, що обʼєкти зʼявились у бакеті.
5. Раз на квартал: скачайте один дамп ІЗ ХМАРИ і проженіть через `scripts/restore-test.sh` — offsite-копія, яку жодного разу не відновлювали, це не бекап, а сподівання.

Periodic Snapshot Task на датасет — корисний додаток (миттєвий відкат), але не заміна: снапшот живе на тому ж диску.

**Навчання з відновлення** (раз на місяць, 2 хвилини, прод не торкається):

```bash
sh scripts/restore-test.sh
```

Підніме одноразовий Postgres, відновить свіжий дамп, покаже кількість проєктів/артефактів/стилів/користувачів і приберe за собою.

**Міграція старих дампів** зі старого docker-тому (один раз після оновлення):

```bash
docker run --rm -v rich-ai_backup_data:/old -v /mnt/Data/Apps/rich-studio/rich-ai/backups:/new alpine sh -c 'cp -a /old/. /new/ 2>/dev/null || true'
```

`.env` в бекап не потрапляє свідомо — там секрети. Збережіть його копію в менеджері паролів: без `JWT_SECRET`/`ADMIN_PASSWORD` відновлення закінчиться переналаштуванням з нуля.


## Вихід назовні без білого IP — Cloudflare Tunnel (шлях Б)

Жодного відкритого порту і жодного засвіченого домашнього IP: `cloudflared`
сам підключається назовні до Cloudflare, TLS терминується у них.

1. Купіть/перенесіть домен на Cloudflare (Registrar або зміна NS-серверів).
2. **Zero Trust → Networks → Tunnels → Create a tunnel** (тип Cloudflared),
   назвіть, скопіюйте **token**.
3. На TrueNAS у `.env`: `CLOUDFLARE_TUNNEL_TOKEN=<token>`, потім:

   ```sh
   cd /mnt/Data/Apps/rich-studio/rich-ai
   docker compose --profile tunnel up -d cloudflared
   ```

4. У майстрі тунелю → **Public hostname**: `studio.ваш-домен`,
   Service: **HTTP**, URL: `web:80` (nginx усередині compose-мережі).
5. OAuth: у GitHub/Google OAuth-застосунках замініть callback на
   `https://studio.ваш-домен/api/auth/{github|google}/callback` і задайте ті ж
   значення в `GITHUB_CALLBACK_URL` / `GOOGLE_CALLBACK_URL`.
6. Через тиждень тиші в логах: `MEDIA_SIGNING=strict`.

Опційний другий замок: **Zero Trust → Access → Applications** — поставити перед
студією ще й Cloudflare Access (SSO-екран до того, як запит взагалі дійде до
nginx). Безкоштовно до 50 користувачів.

Профіль `tls` (Caddy) для цього шляху НЕ потрібен — не вмикайте обидва разом.


## Експорт блоків сторінки в PNG

Деякі майданчики не приймають HTML - потрібні картинки. Кнопка **«Блоки в PNG»**
у вкладці «Перегляд» віддає ZIP, де кожен блок сторінки - окремий PNG (плюс
повний знімок). Рендерить справжній Chromium, тож картинка точно така, як бачить
покупець.

Сервіс необовʼязковий і типово вимкнений (образ із браузером важкий):

```sh
cd /mnt/Data/Apps/rich-studio/rich-ai
docker compose --profile shots up -d --build shots
```

Кнопка зʼявиться одразу. Вимкнути - `docker compose stop shots` або прибрати
`SHOTS_URL` у `.env`.
