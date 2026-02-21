FROM python:3.13-slim

# Install FFmpeg + Tesseract OCR (for OCR signal module)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    tesseract-ocr \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

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
    uv sync --no-install-project

# Copy the rest of the application
COPY README.md ./
COPY src ./src
COPY config ./config

# Install the project
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync

# Environment variables
ENV PYTHONUNBUFFERED=1

# Run the worker
CMD ["uv", "run", "python", "-m", "highlight_worker.main"]
