# ---------- Base builder ----------
FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# ---------- Runtime image ----------
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    BOT_DB_PATH=/data/images.db

RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

RUN useradd -m -u 10001 appuser && \
    mkdir -p /app /data && chown -R appuser:appuser /app /data

WORKDIR /app

COPY --from=builder /usr/local /usr/local
COPY --chown=appuser:appuser . /app

USER appuser

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
 CMD python -c "import os,sys; sys.exit(0 if os.access('/data', os.W_OK) else 1)"

CMD ["python", "bot.py"]
