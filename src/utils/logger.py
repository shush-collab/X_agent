"""Centralized logging utilities for the X automation stack."""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator, Optional

LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - [%(correlation_id)s] - %(message)s"

LOG_LEVELS = {
    "services.crawler": "DEBUG",
    "services.generator": "INFO",
    "services.safety": "WARNING",
}

_DEFAULT_LEVEL_NAME = os.getenv("LOG_LEVEL", "INFO").upper()
_correlation_id_var: ContextVar[str] = ContextVar("correlation_id", default="-")
_MANAGED_HANDLER: Optional[logging.Handler] = None


class CorrelationIdFilter(logging.Filter):
    """Injects the current correlation ID into log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.correlation_id = _correlation_id_var.get("-")
        return True


def set_correlation_id(value: str) -> None:
    """Set the correlation ID for the current context."""

    _correlation_id_var.set(value)


def get_correlation_id(default: str = "-") -> str:
    """Retrieve the current correlation ID."""

    return _correlation_id_var.get(default)


def clear_correlation_id() -> None:
    """Clear the correlation ID for the current context."""

    _correlation_id_var.set("-")


@contextmanager
def correlation_id_context(value: str):
    """Context manager to temporarily set a correlation ID."""

    token = _correlation_id_var.set(value)
    try:
        yield value
    finally:
        _correlation_id_var.reset(token)


def _get_managed_handler() -> logging.Handler:
    global _MANAGED_HANDLER
    if _MANAGED_HANDLER is None:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(LOG_FORMAT))
        handler.addFilter(CorrelationIdFilter())
        handler.setLevel(logging.DEBUG)
        setattr(handler, "_x_automation_managed", True)
        _MANAGED_HANDLER = handler
    return _MANAGED_HANDLER


def _parse_level(level_name: str) -> int:
    candidate = level_name.upper()
    if candidate.isdigit():
        return int(candidate)
    mapping = getattr(logging, "getLevelNamesMapping", None)
    if callable(mapping):
        return mapping().get(candidate, logging.INFO)
    return getattr(logging, "_nameToLevel", {}).get(candidate, logging.INFO)


def _iter_name_hierarchy(logger_name: str) -> Iterator[str]:
    parts = logger_name.split(".")
    for index in range(len(parts), 0, -1):
        yield ".".join(parts[:index])


def _resolve_level(logger_name: str) -> int:
    for candidate in _iter_name_hierarchy(logger_name):
        if candidate in LOG_LEVELS:
            return _parse_level(LOG_LEVELS[candidate])
    return _parse_level(_DEFAULT_LEVEL_NAME)


def get_logger(name: str) -> logging.Logger:
    """Return a configured logger with correlation-aware formatting."""

    logger = logging.getLogger(name)
    handler = _get_managed_handler()
    if not any(getattr(h, "_x_automation_managed", False) for h in logger.handlers):
        logger.addHandler(handler)
    logger.setLevel(_resolve_level(name))
    logger.propagate = False
    return logger


def get_playwright_logger() -> logging.Logger:
    """Return the logger dedicated to Playwright browser activity."""

    browser_logger = get_logger("playwright").getChild("browser")
    if not any(getattr(h, "_x_automation_managed", False) for h in browser_logger.handlers):
        browser_logger.addHandler(_get_managed_handler())
    browser_logger.propagate = False
    return browser_logger


__all__ = [
    "LOG_FORMAT",
    "LOG_LEVELS",
    "get_logger",
    "get_playwright_logger",
    "set_correlation_id",
    "get_correlation_id",
    "clear_correlation_id",
    "correlation_id_context",
]
