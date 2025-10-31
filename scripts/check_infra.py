"""Smoke-test connectivity to local infrastructure services."""

from __future__ import annotations

import asyncio
import os
import sys
from contextlib import closing

import httpx
import psycopg2
import redis


def check_postgres(dsn: str) -> None:
    with closing(psycopg2.connect(dsn)) as conn, conn.cursor() as cur:
        cur.execute("SELECT 1;")
        cur.fetchone()


async def check_ollama(url: str) -> None:
    async with httpx.AsyncClient(timeout=3.0) as client:
        resp = await client.get(f"{url}/api/tags")
        resp.raise_for_status()


def check_redis(url: str) -> None:
    client = redis.Redis.from_url(url)
    if client.ping() is not True:
        raise RuntimeError("Redis ping failed")


async def main() -> int:
    dsn = os.getenv("DATABASE_URL", "postgresql://postgres:password@localhost:5432/x_automation")
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    ollama_url = os.getenv("OLLAMA_URL", "http://localhost:11434")

    try:
        check_postgres(dsn)
        check_redis(redis_url)
        await check_ollama(ollama_url)
    except Exception as exc:  # noqa: BLE001 - surface full error to operator
        print(f"[check_infra] failure: {exc}", file=sys.stderr)
        return 1

    print("[check_infra] postgres, redis, and ollama responded successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
