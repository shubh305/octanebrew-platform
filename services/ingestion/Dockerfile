FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

# Set workdir
WORKDIR /app

# Enable bytecode compilation and set link mode to copy
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy

# Copy only dependency files
COPY pyproject.toml uv.lock ./

# Install dependencies
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project

# Copy the rest of the application
COPY README.md ./
COPY src ./src
# COPY tests ./tests

# Install the project
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen

# Environment variables
ENV PYTHONUNBUFFERED=1

# Run the application
CMD ["uv", "run", "uvicorn", "ingestion.main:app", "--host", "0.0.0.0", "--port", "8001"]
