FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .
COPY config ./config
COPY assets ./assets
COPY main.py ./
COPY alembic.ini ./
COPY migrations ./migrations
COPY docker-entrypoint.sh ./
RUN chmod +x /app/docker-entrypoint.sh
RUN mkdir -p /app/data /app/storage

ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["python", "main.py"]
