FROM python:3.9-slim

RUN apt-get update && apt-get install -y \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN mkdir -p /app/sqlite_data && chmod a+rwx /app/sqlite_data

COPY requirements.txt .
COPY .env .
COPY event_bot.py .

RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt


HEALTHCHECK --interval=30s --timeout=10s \
    CMD python -c "import asyncio; from telegram import Bot; \
    asyncio.run(Bot('${TELEGRAM_BOT_TOKEN}').get_me()) || exit 1"

CMD ["python", "event_bot.py"]
