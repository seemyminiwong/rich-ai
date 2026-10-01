# Ізольований контейнер post-publish аудиту публічного URL.
# НЕ входить в образ API: Lighthouse (Chromium), Lychee і crawler живуть тут,
# запускаються з обмеженнями CPU/RAM/часу (docker-compose, профіль audit) і
# не мають доступу до внутрішньої мережі студії - лише до публічного URL.
FROM python:3.12-slim-trixie

ENV DEBIAN_FRONTEND=noninteractive \
    LIGHTHOUSE_VERSION=13.5.0 \
    LYCHEE_VERSION=v0.24.2 \
    CHROME_PATH=/usr/bin/chromium \
    npm_config_cache=/tmp/npm-cache

RUN apt-get update && apt-get install -y --no-install-recommends \
        chromium nodejs npm curl ca-certificates fonts-liberation \
    && npm install -g "lighthouse@${LIGHTHOUSE_VERSION}" \
    && ARCH="$(uname -m)" && case "$ARCH" in x86_64) LY_ARCH=x86_64-unknown-linux-gnu ;; aarch64) LY_ARCH=aarch64-unknown-linux-gnu ;; esac \
    && curl -fsSL "https://github.com/lycheeverse/lychee/releases/download/${LYCHEE_VERSION}/lychee-${LY_ARCH}.tar.gz" | tar -xz -C /usr/local/bin lychee \
    && apt-get purge -y curl && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

WORKDIR /audit
COPY scripts/audit_public_url.py /audit/audit_public_url.py
RUN useradd -m audit && chown -R audit:audit /audit
USER audit
ENTRYPOINT ["python", "/audit/audit_public_url.py"]
