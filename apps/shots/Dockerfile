# Самодостатній образ: playwright і Chromium в тому самому середовищі, що й
# fastapi/uvicorn. Системні залежності ставимо ЯВНО (не через --with-deps, який
# на slim часом рветься), потім лише сам браузер.
FROM python:3.12-slim

WORKDIR /app
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-browsers

RUN pip install --no-cache-dir \
        fastapi==0.115.12 uvicorn==0.34.2 pydantic==2.11.7 playwright==1.49.0 \
    && python -m playwright install-deps chromium \
    && python -m playwright install chromium

COPY server.py .
EXPOSE 8080
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8080"]
