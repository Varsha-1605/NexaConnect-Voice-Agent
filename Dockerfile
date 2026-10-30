# Agent image for LiveKit Cloud. Built by `lk agent create` / `lk agent deploy`.

# BUILD STAGE: install the dependencies
FROM python:3.13-slim AS builder

# uv, pinned to one version so builds are repeatable
COPY --from=ghcr.io/astral-sh/uv:0.11.6 /uv /uvx /bin/

# Compilers, in case a dependency has no ready-made wheel. They stay in this stage only.
RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0

# Dependencies first: this layer is cached until pyproject.toml or uv.lock change
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-install-project --no-dev

# Then the code (.dockerignore keeps .env, tests, simulations, web and docs out)
COPY . ./
RUN uv sync --locked --no-dev


# PRODUCTION STAGE: only what is needed to run
FROM python:3.13-slim

WORKDIR /app

# Run as a normal user, not root
RUN useradd -m appuser && chown -R appuser:appuser /app
USER appuser

COPY --from=builder --chown=appuser:appuser /app /app

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

# Download the VAD and turn-detector model files now, so a call never waits for them
RUN python agent.py download-files

# `exec` form: the agent receives SIGTERM, so a deploy lets running calls finish
CMD ["python", "agent.py", "start"]
