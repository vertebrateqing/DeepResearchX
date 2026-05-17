# DeepResearchX backend image — uv-managed Python environment.
#
# Build context: ./backend
# Final image runs `uvicorn main:app` on :8000.

FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv

# System deps required by weasyprint (PDF) and pdfplumber font handling
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpango-1.0-0 \
        libpangoft2-1.0-0 \
        libcairo2 \
        libgdk-pixbuf-2.0-0 \
        libffi-dev \
        shared-mime-info \
        fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

# Install uv from the official image
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app

# Resolve and install dependencies first for layer caching.
# Copy only the manifest + lockfile so source edits don't invalidate the install.
# Install with the `pdf` extra so weasyprint can use the system pango/cairo libs
# we provisioned above. Local-embedding (torch) stays out — production uses the
# cloud embedding API.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project --extra pdf

# Copy the application code and install the project itself.
COPY . .
RUN uv sync --frozen --no-dev --extra pdf

ENV PATH="/opt/venv/bin:${PATH}"

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
