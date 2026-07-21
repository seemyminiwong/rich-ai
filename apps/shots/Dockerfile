# Готовий образ Playwright: Chromium і всі системні залежності вже всередині.
FROM mcr.microsoft.com/playwright/python:v1.49.0-jammy

WORKDIR /app
RUN pip install --no-cache-dir fastapi==0.115.12 uvicorn==0.34.2 pydantic==2.11.7
COPY server.py .
EXPOSE 8080
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8080"]
