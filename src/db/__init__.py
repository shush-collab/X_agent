"""Database schema utilities for X Automation System."""

from pathlib import Path

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def load_schema() -> str:
    """Return the SQL schema as a string."""
    return SCHEMA_PATH.read_text(encoding="utf-8")
