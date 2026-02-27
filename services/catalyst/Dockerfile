FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

WORKDIR /app

# Enable bytecode compilation and set link mode to copy
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy

# Copy only dependency files first (for layer caching)
COPY pyproject.toml uv.lock* ./

# Install dependencies (without project)
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-install-project

# Copy application source
COPY README.md ./
COPY src ./src
# COPY workers ./workers

# Install project
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync

ENV PYTHONUNBUFFERED=1

CMD ["uv", "run", "uvicorn", "catalyst.main:app", "--host", "0.0.0.0", "--port", "8002"]
