FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
# Шрифти для інфографіки (Pillow малює текст напряму, без браузера). Roboto -
# фірмовий; якщо в дистрибутиві його немає, лишається DejaVu з кирилицею.
RUN apt-get update \
 && apt-get install -y --no-install-recommends fonts-dejavu-core \
 && (apt-get install -y --no-install-recommends fonts-roboto-unhinted || echo 'roboto unavailable, using dejavu') \
 && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY alembic.ini .
COPY graph ./graph
COPY alembic ./alembic
RUN mkdir -p /app/media
EXPOSE 8000
# --proxy-headers: за Cloudflare Tunnel оригінальна схема запиту (https)
# приходить у X-Forwarded-Proto. Без цього request.base_url будує http://
# на https-сторінці, і OAuth-провайдер відбиває redirect_uri. Довіряти
# заголовкам можна: порт 8000 опублікований лише на 127.0.0.1, ззовні до
# API йдуть тільки через nginx, який ці заголовки й ставить.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
