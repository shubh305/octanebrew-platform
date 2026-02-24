FROM python:3.13-slim

WORKDIR /app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

COPY pyproject.toml ./
COPY README.md ./
COPY src ./src

# Install dependencies
RUN uv sync --no-install-project

# Install project
RUN uv sync

# Run app
CMD ["uv", "run", "python", "-m", "analytics.main"]
