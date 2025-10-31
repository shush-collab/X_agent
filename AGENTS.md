# Repository Guidelines

## Project Structure & Module Organization
Source code lives in `src/`, with `src/main.py` as the primary entry point for orchestrating agents or experiments. Use `src/agents/` and `src/utils/` subpackages when you add more modules to keep responsibilities clear. Data artifacts belong under `data/`; keep raw inputs in `data/raw/` and write derived results to `data/processed/`. The `img/` folder stores reference imagery or diagrams, while the `credentials/` directory is reserved for local-only secrets (never commit real keys). Docker-related files (`Dockerfile`, `docker-compose.yml`) define production-like environments; keep any service-specific configs beside them.

## Build, Test, and Development Commands
Create an isolated environment before installing dependencies:
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```
Run the agent locally with `python -m src.main`. If you rely on containers, `docker compose up --build` provisions the full stack described in `docker-compose.yml`. Keep `requirements.txt` synchronized with the environment by running `pip freeze > requirements.txt` after dependency updates.

## Coding Style & Naming Conventions
Follow PEP 8 with four-space indentation and descriptive, lowercase module names (e.g., `src/agents/interaction_loop.py`). Use type hints for all public functions to clarify interfaces, and prefer dataclasses for structured message payloads. Before committing, format Python files with `black src tests` and enforce import order via `isort`. Keep functions cohesive; place shared utilities in `src/utils/` rather than duplicating logic.

## Testing Guidelines
Adopt `pytest` for unit and integration tests. Place new test modules under `tests/`, mirroring the `src/` layout (`tests/test_main.py`, `tests/agents/test_scheduler.py`). Name tests with intent-revealing verbs such as `test_handles_missing_credentials`. Run the suite locally using `pytest --maxfail=1` and target high coverage on agent decision paths. When you add external integrations, introduce lightweight fakes so tests remain deterministic.

## Commit & Pull Request Guidelines
Use concise, imperative commit messages (`Add scheduler for multi-agent runs`) and keep commits focused on a single concern. Reference issue IDs in the subject when applicable (`Add scheduler for multi-agent runs (#42)`). Pull requests should describe the problem, summarize the approach, and link to any design docs or tracking tickets. Include validation notes (commands run, screenshots, logs) so reviewers can verify the change quickly. Ensure CI passes and that new configuration steps are documented in this guide or inline README updates.
