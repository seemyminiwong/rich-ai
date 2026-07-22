# Debian BOOKWORM (стабільний, офіційно підтримується Playwright — apt-список
# сходиться), а не trixie зі slim, де падало на ttf-ubuntu-font-family.
# playwright ставимо ТИМ САМИМ pip, що й fastapi, тож "import playwright"
# бачить пакет (на офіційному MS-образі він жив в іншому python).
FROM python:3.12-slim-bookworm

WORKDIR /app
RUN pip install --no-cache-dir --break-system-packages \
        fastapi==0.115.12 uvicorn==0.34.2 pydantic==2.11.7 playwright==1.49.0 \
    && playwright install --with-deps chromium \
    && python -c "import playwright, fastapi, uvicorn, pydantic; print('imports ok')"

COPY server.py .
EXPOSE 8080
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8080"]
