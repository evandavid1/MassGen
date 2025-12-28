# MassGen Railway Deployment Guide

This guide documents how to deploy MassGen to Railway.

## Overview

MassGen's web UI is deployed to Railway using Nixpacks for automated builds. The deployment uses:

- **Python 3.11** runtime
- **uv** for fast dependency installation from `pyproject.toml`
- **FastAPI + Uvicorn** for the web server
- **EU West (Amsterdam)** region

## Prerequisites

- A Railway account (https://railway.com)
- A GitHub repository with your MassGen fork
- API keys for the AI providers you want to use (Claude, Gemini, OpenAI, etc.)

## Project Structure

Key files for deployment:

```
MassGen/
├── pyproject.toml      # Python dependencies (single source of truth)
├── nixpacks.toml       # Railway/Nixpacks build configuration
├── Procfile            # Process definition (fallback)
└── massgen/
    └── frontend/
        └── web/        # Web UI source code
```

## Configuration Files

### nixpacks.toml

This file configures the Nixpacks build process:

```toml
[phases.setup]
nixPkgs = ["python311"]
cmds = ["pip install uv"]

[phases.install]
cmds = ["uv pip install . --system"]

[start]
cmd = "python -m massgen.cli --web --web-host 0.0.0.0 --web-port $PORT"
```

**Key points:**
- Uses `uv` for fast, reliable dependency installation
- Installs directly from `pyproject.toml` (no separate requirements.txt needed)
- Starts the web UI with the correct host/port binding

### Procfile

Fallback process definition:

```
web: python -m massgen.cli --web --web-host 0.0.0.0 --web-port $PORT
```

## Deployment Steps

### 1. Initial Setup

1. Fork the MassGen repository to your GitHub account
2. Create a new project in Railway
3. Connect your GitHub repository
4. Railway will auto-detect Python and use Nixpacks

### 2. Configure Environment Variables

In Railway's service settings, add your API keys:

```
ANTHROPIC_API_KEY=sk-ant-...
GOOGLE_API_KEY=...
OPENAI_API_KEY=sk-...
```

Add any other provider keys as needed (GROQ_API_KEY, XAI_API_KEY, etc.)

### 3. Configure Service Settings

1. Go to **Service Settings** > **Deploy**
2. Verify the **Custom Start Command** is set to:
   ```
   python -m massgen.cli --web --web-host 0.0.0.0 --web-port $PORT
   ```
3. Select your preferred **Region** (e.g., EU West)

### 4. Deploy

Push to your main branch - Railway will automatically:
1. Detect changes via GitHub webhook
2. Run Nixpacks build
3. Install dependencies with uv
4. Start the web server
5. Route traffic to your domain

## Troubleshooting

### "command not found: massgen"

**Cause:** The start command is using `massgen` directly instead of the Python module.

**Fix:** Change the start command to:
```
python -m massgen.cli --web --web-host 0.0.0.0 --web-port $PORT
```

### "ModuleNotFoundError: No module named 'X'"

**Cause:** A dependency is missing from `pyproject.toml`.

**Fix:**
1. Add the missing dependency to `pyproject.toml`
2. Commit and push to trigger a new deployment

### "Web UI dependencies not installed"

**Cause:** FastAPI or Uvicorn not installed.

**Fix:** Ensure `pyproject.toml` includes:
```toml
dependencies = [
    ...
    "fastapi>=0.109.0",
    "uvicorn[standard]>=0.27.0",
    ...
]
```

### Application crashes on startup

Check the **Deploy Logs** in Railway for the specific error. Common issues:
- Missing API keys in environment variables
- Port binding issues (ensure using `$PORT`)
- Memory limits exceeded

## Local Development

To run the web UI locally:

```bash
# Install dependencies
uv pip install -e .

# Run the web server
python -m massgen.cli --web

# Or with specific host/port
python -m massgen.cli --web --web-host 0.0.0.0 --web-port 8080
```

## Architecture Notes

### Why uv over pip?

- **Speed:** uv is 10-100x faster than pip
- **Single source:** Uses `pyproject.toml` directly, no requirements.txt sync issues
- **Reproducibility:** Better dependency resolution

### Why python -m massgen.cli?

The `massgen` command-line entry point requires the package to be installed with scripts in PATH. Using `python -m massgen.cli` works regardless of PATH configuration and is more reliable in containerized environments.

## URLs

- **Production:** https://web-production-0115.up.railway.app
- **Railway Dashboard:** https://railway.com/project/3392ae31-f546-443b-9a0d-2fc752d3e3c2

## Updating Dependencies

1. Edit `pyproject.toml` to add/update dependencies
2. Commit and push to trigger deployment
3. Railway will automatically rebuild with new dependencies

No need to maintain a separate `requirements.txt` - `pyproject.toml` is the single source of truth.
