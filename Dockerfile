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
COPY data/summary.txt data/summary.txt

# data/ is volume-mounted at runtime; pre-create dir so mount point is owned by appuser
RUN mkdir -p /app/data && chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

ENTRYPOINT ["tini", "--"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
