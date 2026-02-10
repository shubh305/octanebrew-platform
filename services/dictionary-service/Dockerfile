FROM python:3.12-slim

ENV UV_PYTHON_PREFERENCE=system
ENV UV_PYTHON=python3.12

WORKDIR /app

# Install system dependencies (Java for LanguageTool)
RUN apt-get update && apt-get install -y \
    default-jre \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

# Copy only dependency files
COPY pyproject.toml ./

# Install all dependencies 
RUN uv sync --no-install-project

# Download additional NLP resources (LanguageTool & TextBlob)
RUN uv run --no-project python -m textblob.download_corpora \
    && uv run --no-project python -c "import language_tool_python; language_tool_python.LanguageTool('en-US')"

# Copy the rest of the source code
COPY . .

# 5. Final sync to link the project
RUN uv sync

# Run app
CMD ["uv", "run", "uvicorn", "dictionary_service.main:app", "--host", "0.0.0.0", "--port", "8000"]
