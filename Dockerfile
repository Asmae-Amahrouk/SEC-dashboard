# SEC Pulse: dashboard + news collector in one small container.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080 \
    REFRESH_HOURS=3 \
    WINDOW_DAYS=30

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
 && useradd --system --uid 10001 --home /app secpulse

COPY config ./config
COPY scraper ./scraper
COPY docs ./docs
RUN chown -R secpulse:secpulse /app/docs/data

USER secpulse
VOLUME ["/app/docs/data"]
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import os,urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8080\")}/healthz', timeout=4)" || exit 1

CMD ["python", "scraper/serve.py"]
