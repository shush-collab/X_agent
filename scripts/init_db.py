"""Initialize PostgreSQL schema for the X Automation System."""

from __future__ import annotations

import argparse
import os
import sys

import psycopg2
from psycopg2.extensions import connection

from src.db import load_schema


def init_db(conn: connection) -> None:
    """Apply the schema file to the target database."""
    with conn, conn.cursor() as cur:
        cur.execute(load_schema())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dsn",
        default=os.getenv("DATABASE_URL", "postgresql://postgres:password@localhost:5432/x_automation"),
        help="PostgreSQL DSN; defaults to DATABASE_URL env var.",
    )
    args = parser.parse_args()

    try:
        with psycopg2.connect(args.dsn) as conn:
            init_db(conn)
    except psycopg2.Error as exc:
        print(f"[init_db] failed: {exc}", file=sys.stderr)
        return 1

    print("[init_db] database schema applied successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
