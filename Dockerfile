FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates npm \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml /app/
COPY gateway /app/gateway
RUN pip install --no-cache-dir .

RUN npm install -g @anthropic-ai/claude-code @openai/codex

RUN useradd --create-home --shell /bin/bash gateway \
    && mkdir -p /state /work /accounts/claude /accounts/codex \
    && chown -R gateway:gateway /state /work /accounts

USER gateway

EXPOSE 8080

CMD ["uvicorn", "gateway.app:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
