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

# Match the host user's uid/gid so bind-mounted account dirs (Claude/Codex
# credentials) are writable from inside the container and land on the host
# owned by the invoking user. compose passes these from .env (HOST_UID/HOST_GID).
ARG HOST_UID=1000
ARG HOST_GID=1000

RUN groupadd -g ${HOST_GID} gateway \
    && useradd --create-home --shell /bin/bash -u ${HOST_UID} -g ${HOST_GID} gateway \
    && mkdir -p /state /work /accounts/claude /accounts/codex \
    && chown -R gateway:gateway /state /work /accounts

USER gateway

EXPOSE 8080

CMD ["uvicorn", "gateway.app:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
