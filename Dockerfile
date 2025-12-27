# ---------- Base builder ----------
FROM python:3.11-alpine AS builder

# Install build dependencies for C-extensions if needed
RUN apk add --no-cache build-base

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ---------- Runtime image ----------
FROM python:3.11-alpine

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    botDbPath=/data/wordleSwapBot.db \
    PYTHONPATH=/app

# Create app directory and data directory for the SQLite database
RUN mkdir -p /app /data && \
    addgroup -S appgroup && adduser -S appuser -G appgroup && \
    chown -R appuser:appgroup /app /data

WORKDIR /app

# Copy dependencies from builder
COPY --from=builder /install /usr/local
# Copy project files with correct ownership
COPY --chown=appuser:appgroup . /app

# The database should persist here
VOLUME /data

USER appuser

# Healthcheck ensures the /data directory is writable by the appuser
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
 CMD python -c "import os,sys; sys.exit(0 if os.access('/data', os.W_OK) else 1)"

CMD ["python", "bot.py"]