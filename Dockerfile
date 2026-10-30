# agent image for LiveKit Cloud

# build stage
FROM python:3.13-slim AS builder

# uv, pinned
COPY --from=ghcr.io/astral-sh/uv:0.11.6 /uv /uvx /bin/

# compilers for dependencies without wheels
RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0

# dependencies first, cached layer
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-install-project --no-dev

# then the code
COPY . ./
RUN uv sync --locked --no-dev


# production stage
FROM python:3.13-slim

WORKDIR /app

# run as a normal user
RUN useradd -m appuser && chown -R appuser:appuser /app
USER appuser

COPY --from=builder --chown=appuser:appuser /app /app

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

# download model files at build time
RUN python agent.py download-files

# exec form so the agent gets SIGTERM
CMD ["python", "agent.py", "start"]
