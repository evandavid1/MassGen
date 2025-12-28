# MassGen Railway Deployment Guide

This guide documents how to deploy MassGen to Railway.

## Overview

MassGen's web UI is deployed to Railway using Nixpacks for automated builds. The deployment uses:

- **Python 3.11** runtime
- **Node.js 20** for openskills CLI (Anthropic Skills Collection)
- **uv** for fast dependency installation from `pyproject.toml`
- **FastAPI + Uvicorn** for the web server
- **EU West (Amsterdam)** region

## Git Remotes

This is a fork of the upstream MassGen repository:

- **myfork**: `git@github.com:evandavid1/MassGen.git` - Push changes here
- **origin**: `https://github.com/massgen/MassGen.git` - Upstream (read-only)

```bash
# Always push to myfork, not origin
git push myfork main
```

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
nixPkgs = ["python311", "uv", "nodejs_20"]

[phases.install]
cmds = [
    "uv venv /opt/venv",
    "uv pip install . --python /opt/venv/bin/python",
    "HOME=/app npx openskills install anthropics/skills --universal -y || true"
]

[start]
cmd = "/opt/venv/bin/python -m massgen.cli --web --web-host 0.0.0.0 --web-port $PORT"
```

**Key points:**
- Uses `uv` as a Nix package for fast, reliable dependency installation
- Creates virtual environment in `/opt/venv` (not `.venv` - see note below)
- Installs directly from `pyproject.toml` (no separate requirements.txt needed)
- Includes Node.js 20 for openskills CLI (npm is bundled with nodejs)
- Uses `npx` to run openskills (npm global bin not in PATH during build)
- Sets `HOME=/app` so skills install to `/app/.agent/skills/` which persists to runtime
- Uses `|| true` so build succeeds even if skills installation fails
- Starts the web UI with the correct host/port binding

**Important notes:**
- In Nix, `npm` is bundled with `nodejs_20` - do not add `npm` as a separate package
- **Use `/opt/venv` not `.venv`**: Nixpacks runs `COPY . /app` after the install phase, which overwrites any `.venv` in the project directory. Using `/opt/venv` places the virtual environment outside the app directory where it won't be overwritten.

### Procfile

Fallback process definition (not used when nixpacks.toml is present):

```
web: python -m massgen.cli --web --web-host 0.0.0.0 --web-port $PORT
```

## Common Pitfalls (What NOT to Do)

These mistakes were discovered during setup. Avoid repeating them:

| ❌ Don't Do This | ✅ Do This Instead | Why |
|------------------|-------------------|-----|
| Use `pip` or `python -m pip` | Use `uv` as a Nix package | Nix Python is "externally managed" and blocks pip installs |
| Create venv in `.venv` | Create venv in `/opt/venv` | Nixpacks runs `COPY . /app` after install, overwriting `.venv` |
| Add `npm` to nixPkgs | Only add `nodejs_20` | npm is bundled with nodejs in Nix |
| Use default "Railpack" builder | Change to "Nixpacks" builder | Railpack ignores `nixpacks.toml` entirely |
| Use `uv pip install --system` | Use `uv venv` + `uv pip install --python` | Nix has immutable `/nix/store` filesystem |
| Use `massgen` command directly | Use `python -m massgen.cli` | Entry point scripts may not be in PATH |
| Install npm packages at runtime | Install during build with `HOME=/app npx` | npm global bin not in PATH; skills must install to /app to persist |

### Nix/Nixpacks Constraints

Nixpacks uses Nix under the hood, which has specific constraints:

1. **Immutable filesystem**: The `/nix/store` is read-only. You cannot install packages globally.
2. **Externally managed Python**: Nix Python blocks `pip install --system` to prevent conflicts.
3. **Build order**: Nixpacks copies source files AFTER running install commands, so anything in the project directory gets overwritten.
4. **Package bundling**: Some packages include others (e.g., `nodejs_20` includes `npm`).

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

1. Go to **Service Settings** > **Build**
2. **CRITICAL:** Change **Builder** from "Railpack" to "Nixpacks"
   - Railpack (default) ignores `nixpacks.toml` and auto-detects Python
   - Nixpacks properly reads `nixpacks.toml` for custom packages (Node.js, uv, etc.)
3. Go to **Service Settings** > **Deploy**
4. Verify the **Custom Start Command** is set to:
   ```
   /opt/venv/bin/python -m massgen.cli --web --web-host 0.0.0.0 --web-port $PORT
   ```
5. Select your preferred **Region** (e.g., EU West)

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

### Dependencies not installed (ModuleNotFoundError at runtime)

**Cause:** The virtual environment was created in `.venv` which gets overwritten by Nixpacks' `COPY . /app` command after installation.

**Fix:** Use `/opt/venv` instead of `.venv` in nixpacks.toml:
```toml
[phases.install]
cmds = ["uv venv /opt/venv", "uv pip install . --python /opt/venv/bin/python"]

[start]
cmd = "/opt/venv/bin/python -m massgen.cli --web --web-host 0.0.0.0 --web-port $PORT"
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

## Skills Configuration

MassGen supports skills - specialized capabilities that extend agent functionality. Skills are installed via the `openskills` CLI.

### How Skills Are Installed

Skills are installed during the **build phase** using this command in `nixpacks.toml`:

```bash
HOME=/app npx openskills install anthropics/skills --universal -y || true
```

**Why this specific approach:**

| Challenge | Solution |
|-----------|----------|
| npm global packages not in PATH | Use `npx` to run openskills directly |
| Skills install to `~/.agent/skills/` | Set `HOME=/app` to install to `/app/.agent/skills/` |
| Home directory doesn't persist to runtime | Installing to `/app/` ensures persistence |
| Build shouldn't fail if skills fail | Use `|| true` to continue on error |

### Skills Storage Locations

MassGen looks for skills in these locations (in order):

1. **Built-in**: `massgen/skills/` (8 skills bundled with MassGen)
2. **User**: `~/.agent/skills/` (home directory - where openskills installs by default)
3. **Project**: `.agent/skills/` (relative to working directory)

In Railway deployment, we set `HOME=/app` during build so skills install to `/app/.agent/skills/`, which persists because `/app` is the container's working directory.

### Currently Installed Skills

After deployment, the following skills are available:

- **Built-in**: 8 skills (bundled with MassGen)
- **Anthropic Skills Collection**: 17 skills (code analysis, research, etc.)
- **Crawl4AI**: 1 skill (web crawling/scraping)
- **Total**: 26 skills

### Adding More Skills

To add additional skill packages:

1. Add the installation command to `nixpacks.toml`:
   ```toml
   [phases.install]
   cmds = [
       "uv venv /opt/venv",
       "uv pip install . --python /opt/venv/bin/python",
       "HOME=/app npx openskills install anthropics/skills --universal -y || true",
       "HOME=/app npx openskills install another/skill-package --universal -y || true"
   ]
   ```

2. Commit and push to trigger a rebuild

### Enabling Skills in YAML Config

To use skills in your MassGen configuration:

```yaml
coordination:
  use_skills: true
  massgen_skills:
    - skill_name_1
    - skill_name_2
```

See the MassGen documentation for available skill names and configuration options.

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
