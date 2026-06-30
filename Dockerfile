# Stage 1: build deps into /install
FROM python:3.12-slim AS builder

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# Stage 2: lean runtime
FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends tini \
    && rm -rf /var/lib/apt/lists/*

RUN adduser --disabled-password --uid 10001 appuser

WORKDIR /app

COPY --from=builder /install /usr/local
COPY app/ app/
COPY scripts/ scripts/
# summary.txt → system prompt; actuators.json → ingest source. Both must be baked in
# because the data/ volume mounts empty on first run and the entrypoint ingests from them.
COPY data/summary.txt data/summary.txt
COPY data/actuators.json data/actuators.json

# data/ (db, chroma) is volume-mounted at runtime; pre-create so the mount is owned by appuser
RUN mkdir -p /app/data && chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

# tini reaps zombies + forwards signals; entrypoint ingests on first boot then serves.
ENTRYPOINT ["tini", "--", "sh", "scripts/docker-entrypoint.sh"]
