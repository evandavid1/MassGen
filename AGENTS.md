# Repository Guidelines

## Project Structure & Module Organization
- `massgen/` contains the core Python package (backends, tools, adapters, session logic, CLI).
- `massgen/tests/` holds pytest-based unit and integration tests plus case-study fixtures.
- `massgen/configs/` and `massgen/v1/examples/` provide YAML configuration examples.
- `docs/` is the Sphinx documentation source; `docs/source/` is the main content root.
- `webui/` is the Vite + React frontend; `webui/src/` contains UI components and pages.
- `scripts/` includes validation and automation utilities used by Makefile targets.

## Build, Test, and Development Commands
- `uv venv && uv pip install -e . && uv pip install -e ".[dev]"` sets up the Python dev environment.
- `make test` runs the full pytest suite; `make lint` runs flake8 + mypy; `make format` runs black + isort.
- `uv run pytest -x -q -m "not expensive and not integration and not docker" --tb=no` runs the default fast test subset.
- `make docs-build` or `make docs-serve` builds/serves documentation; `make docs-check` validates links + duplication.
- `cd webui && npm install && npm run dev` starts the frontend; `npm run build` builds it.

## Coding Style & Naming Conventions
- Python formatting is enforced by **black** (line length 79) and **isort**.
- Linting uses **flake8**, **pylint**, and **mypy**; run via `pre-commit` or `make lint`.
- Tests follow `test_*.py` naming and live under `massgen/tests/`.
- TypeScript/React in `webui/` uses ESLint; keep components in `webui/src/components/` and pages in `webui/src/pages/`.

## Testing Guidelines
- Primary framework is **pytest**; use markers: `@pytest.mark.integration`, `@pytest.mark.expensive`, `@pytest.mark.docker`.
- Default CI skips marked tests; add markers for API-calling or slow tests and keep unit tests fast.
- Example targeted run: `uv run pytest massgen/tests/test_specific.py`.

## Commit & Pull Request Guidelines
- Recent history shows short, imperative messages (e.g., “Fix …”, “Add …”) plus merge commits.
- CONTRIBUTING recommends conventional prefixes: `feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `style:`, `perf:`, `ci:`.
- PRs should target `dev/v0.1.31` (or `main` if that branch is missing), include **What/Why/How/Testing**, and add screenshots for UI changes.
- Ensure pre-commit checks and relevant tests pass before submitting.

## Configuration & Security Tips
- Store provider keys in `.env` (see README) and avoid committing secrets; pre-commit blocks private keys.
- When adding new config options or backends, update the config validator and add tests.
