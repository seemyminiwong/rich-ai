# Самодостатній образ: playwright і Chromium ставимо В ТЕ САМЕ середовище,
# що й fastapi/uvicorn. Раніше базовий образ Microsoft тримав playwright в
# окремому venv, тож "import playwright" падав ModuleNotFoundError.
FROM python:3.12-slim

WORKDIR /app
RUN pip install --no-cache-dir \
        fastapi==0.115.12 uvicorn==0.34.2 pydantic==2.11.7 playwright==1.49.0 \
    && playwright install --with-deps chromium

COPY server.py .
EXPOSE 8080
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8080"]
