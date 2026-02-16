FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

# Set workdir
WORKDIR /app

# Enable bytecode compilation and set link mode to copy
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy
ENV PYTHONUNBUFFERED=1

# Install system dependencies (Java for LanguageTool)
RUN apt-get update && apt-get install -y \
    default-jre \
    && rm -rf /var/lib/apt/lists/*

# Copy only dependency files
COPY pyproject.toml ./

# Install dependencies
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-install-project

# Download additional NLP resources (LanguageTool & TextBlob)
RUN --mount=type=cache,target=/root/.cache/uv \
    uv run --no-project python -m textblob.download_corpora \
    && uv run --no-project python -c "import language_tool_python; language_tool_python.LanguageTool('en-US')"

# Copy the rest of the application
COPY README.md ./
COPY src ./src

# Install the project
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync

# Run the application
CMD ["uv", "run", "uvicorn", "dictionary_service.main:app", "--host", "0.0.0.0", "--port", "8000"]
