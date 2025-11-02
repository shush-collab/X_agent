# GOAL: One-time project initialization and environment validation
# PURPOSE: Create database schema, test connections, ensure system readiness
# RESPONSIBILITY: Turn fresh clone into working system in one command

"""Project bootstrap script for the X automation stack."""

from __future__ import annotations

import asyncio
import logging
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Sequence


LOGGER = logging.getLogger("x_automation.setup")


def _load_dotenv(env_path: Path) -> None:
    try:
        from dotenv import load_dotenv
    except ImportError as exc:  # pragma: no cover - defensive guard
        raise SystemExit(
            "python-dotenv is required for setup. Install dependencies first."
        ) from exc

    if env_path.exists():
        load_dotenv(env_path)
        LOGGER.info("Loaded environment variables from %s", env_path)
    else:
        LOGGER.warning(
            "Environment file %s not found. Using system environment only.", env_path
        )


def _ensure_env_vars(required_vars: Sequence[str]) -> None:
    missing = [name for name in required_vars if not _get_env(name)]
    if missing:
        raise SystemExit(
            "Missing required environment variables: "
            + ", ".join(sorted(missing))
        )
    LOGGER.info("All required environment variables are present.")


def _get_env(name: str) -> str | None:
    from os import getenv

    value = getenv(name)
    if value:
        return value.strip()
    return None


async def _check_postgres(dsn: str) -> None:
    try:
        import asyncpg
    except ImportError as exc:  # pragma: no cover - defensive guard
        raise SystemExit(
            "asyncpg is required to verify PostgreSQL connectivity. "
            "Install project requirements first."
        ) from exc

    LOGGER.info("Verifying PostgreSQL connectivity...")
    conn = await asyncpg.connect(dsn, timeout=10)
    try:
        await conn.execute("SELECT 1;")
        LOGGER.info("PostgreSQL connection successful.")
    finally:
        await conn.close()


async def _check_redis(url: str) -> None:
    try:
        import redis.asyncio as redis
    except ImportError as exc:  # pragma: no cover - defensive guard
        raise SystemExit(
            "redis-py is required to verify Redis connectivity. "
            "Install project requirements first."
        ) from exc

    LOGGER.info("Verifying Redis connectivity...")
    client = redis.from_url(url)
    try:
        pong = await client.ping()
        if pong:
            LOGGER.info("Redis connection successful.")
    finally:
        await client.close()


def _ensure_playwright_cli() -> None:
    if shutil.which("playwright"):
        LOGGER.info("Playwright CLI detected.")
    else:
        LOGGER.warning(
            "Playwright CLI not found. Install browsers later with 'playwright install'."
        )


def _run_alembic_if_configured(project_root: Path) -> None:
    alembic_ini = project_root / "alembic.ini"
    if not alembic_ini.exists():
        LOGGER.info(
            "No alembic.ini found at %s. Skipping database migrations.", alembic_ini
        )
        return

    LOGGER.info("Running database migrations via Alembic...")
    result = subprocess.run(
        ["alembic", "upgrade", "head"],
        cwd=project_root,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        LOGGER.error("Alembic failed: %s", result.stderr.strip())
        raise SystemExit("Alembic migration failed.")  # pragma: no cover

    LOGGER.info("Alembic migrations applied successfully.")


def _ensure_python_version(min_major: int = 3, min_minor: int = 10) -> None:
    if sys.version_info < (min_major, min_minor):
        raise SystemExit(
            f"Python {min_major}.{min_minor}+ is required; "
            f"detected {sys.version_info.major}.{sys.version_info.minor}."
        )
    LOGGER.info("Python runtime version is compatible.")


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s - %(message)s",
    )

    project_root = Path(__file__).resolve().parents[1]
    env_path = project_root / ".env"

    _ensure_python_version()
    _load_dotenv(env_path)

    required_env = (
        "DATABASE_URL",
        "REDIS_URL",
        "PERPLEXITY_API_KEY",
        "PERPLEXITY_MODEL",
    )
    _ensure_env_vars(required_env)

    dsn = _get_env("DATABASE_URL")
    redis_url = _get_env("REDIS_URL")
    assert dsn is not None  # for type-checkers
    assert redis_url is not None

    await _check_postgres(dsn)
    await _check_redis(redis_url)

    _ensure_playwright_cli()
    _run_alembic_if_configured(project_root)

    LOGGER.info("Setup completed successfully. You're ready to develop!")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:  # pragma: no cover - user initiated abort
        raise SystemExit("Setup interrupted by user.")
