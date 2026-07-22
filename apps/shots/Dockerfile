# Офіційний образ Playwright на Ubuntu Jammy: Chromium і ВСІ системні залежності
# (шрифти тощо) вже всередині — на debian-slim install-deps падав на
# ttf-ubuntu-font-family. Playwright тут лежить у системному python; ставимо
# fastapi/uvicorn ТИМ САМИМ pip, тож "import playwright" точно бачить пакет.
FROM mcr.microsoft.com/playwright/python:v1.49.0-jammy

WORKDIR /app
RUN pip install --no-cache-dir --break-system-packages \
        fastapi==0.115.12 uvicorn==0.34.2 pydantic==2.11.7 \
    && python -c "import playwright, fastapi, uvicorn, pydantic; print('imports ok')"

COPY server.py .
EXPOSE 8080
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8080"]
