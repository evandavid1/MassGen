# MassGen Web Server for Railway
# Mirrors nixpacks.toml setup, but without baking secrets into the image.
# Railway injects environment variables at runtime.

FROM python:3.11-slim

# Install system dependencies (matches nixpacks nixPkgs)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    git \
    nodejs \
    npm \
    && rm -rf /var/lib/apt/lists/*

# Install uv (matches nixpacks)
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:${PATH}"

# Set working directory
WORKDIR /app

# Copy source code
COPY . .

# Install package (matches nixpacks.toml phases.install)
RUN uv venv /opt/venv && \
    uv pip install . --python /opt/venv/bin/python

# Install openskills and Anthropic skills (matches nixpacks.toml)
RUN npm install -g openskills && \
    HOME=/app npx openskills install anthropics/skills --universal -y || true

# Activate virtual environment
ENV PATH="/opt/venv/bin:${PATH}"
ENV PYTHONUNBUFFERED=1

# NOTE: No ARG or ENV for secrets - Railway injects them at runtime

# Start command (matches nixpacks.toml start.cmd)
CMD ["sh", "-c", "/opt/venv/bin/python -m massgen.cli --web --web-host 0.0.0.0 --web-port ${PORT}"]
