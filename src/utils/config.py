"""Lightweight configuration helpers using environment variables and JSON files."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from dotenv import load_dotenv

from src.utils.logger import get_logger

LOGGER = get_logger("utils.config")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = PROJECT_ROOT / "config"
DEFAULT_TARGETS_PATH = CONFIG_DIR / "targets.json"
DEFAULT_BLOCKLIST_PATH = CONFIG_DIR / "blocklist.txt"


@dataclass(frozen=True)
class XAccount:
    username: str
    password: str


@dataclass(frozen=True)
class RateLimitSettings:
    crawl_cooldown_minutes: int = 5
    post_base_delay_minutes: int = 5
    post_jitter_max_minutes: int = 10
    account_rotation_enabled: bool = True


@dataclass(frozen=True)
class SafetySettings:
    manual_review_threshold: float = 0.85
    content_min_length: int = 10
    content_max_length: int = 280
    enable_manual_review: bool = False


@dataclass(frozen=True)
class EngagementThreshold:
    min_likes: int = 0
    min_retweets: int = 0


@dataclass(frozen=True)
class TargetsConfig:
    keywords: List[str] = field(default_factory=list)
    topic_clusters: Dict[str, List[str]] = field(default_factory=dict)
    hashtags: List[str] = field(default_factory=list)
    languages: List[str] = field(default_factory=lambda: ["en"])
    sources: List[str] = field(default_factory=list)
    content_types: List[str] = field(default_factory=list)
    time_window_days: int = 1
    engagement_threshold: EngagementThreshold = field(default_factory=EngagementThreshold)
    exclude_keywords: List[str] = field(default_factory=list)
    exclude_users: List[str] = field(default_factory=list)
    strict_match_phrases: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class Settings:
    database_url: str
    redis_url: str
    perplexity_api_key: str
    perplexity_model: str
    posts_per_hour: int
    daily_post_cap: int
    app_env: str
    log_level: str
    playwright_headless: bool
    rate_limit: RateLimitSettings
    safety: SafetySettings
    x_accounts: List[XAccount] = field(default_factory=list)

    @classmethod
    def from_env(cls, env: Optional[Mapping[str, str]] = None) -> "Settings":
        load_dotenv()
        raw_env: Mapping[str, str]
        raw_env = env or os.environ

        def require(name: str) -> str:
            value = raw_env.get(name, "").strip()
            if not value:
                raise ValueError(f"Environment variable {name} must be set")
            return value

        def require_prefixed(name: str, prefix: str) -> str:
            value = require(name)
            if not value.startswith(prefix):
                raise ValueError(f"{name} must start with '{prefix}'")
            return value

        database_url = require_prefixed("DATABASE_URL", "postgresql://")
        redis_url = require_prefixed("REDIS_URL", "redis://")
        perplexity_api_key = require("PERPLEXITY_API_KEY")
        perplexity_model = raw_env.get("PERPLEXITY_MODEL", "llama-3.1-sonar-small-128k-online")
        posts_per_hour = _coerce_int(raw_env.get("POSTS_PER_HOUR"), default=2, minimum=1, maximum=10, name="POSTS_PER_HOUR")
        daily_post_cap = _coerce_int(raw_env.get("DAILY_POST_CAP"), default=20, minimum=1, maximum=50, name="DAILY_POST_CAP")
        app_env = raw_env.get("APP_ENV", "production").lower()

        log_level = raw_env.get("LOG_LEVEL")
        if log_level:
            log_level = log_level.upper()
        else:
            log_level = "DEBUG" if app_env == "development" else "INFO"

        playwright_headless_env = raw_env.get("PLAYWRIGHT_HEADLESS")
        if playwright_headless_env is None:
            playwright_headless = app_env != "development"
        else:
            playwright_headless = playwright_headless_env.lower() in {"1", "true", "yes"}

        rate_limit = RateLimitSettings(
            crawl_cooldown_minutes=_coerce_int(raw_env.get("CRAWL_COOLDOWN_MINUTES"), default=5, minimum=1, maximum=60, name="CRAWL_COOLDOWN_MINUTES"),
            post_base_delay_minutes=_coerce_int(raw_env.get("POST_BASE_DELAY_MINUTES"), default=5, minimum=1, maximum=60, name="POST_BASE_DELAY_MINUTES"),
            post_jitter_max_minutes=_coerce_int(raw_env.get("POST_JITTER_MAX_MINUTES"), default=10, minimum=0, maximum=60, name="POST_JITTER_MAX_MINUTES"),
            account_rotation_enabled=_coerce_bool(raw_env.get("ACCOUNT_ROTATION_ENABLED"), default=True),
        )

        safety = SafetySettings(
            manual_review_threshold=_coerce_float(raw_env.get("MANUAL_REVIEW_THRESHOLD"), default=0.85, minimum=0.0, maximum=1.0, name="MANUAL_REVIEW_THRESHOLD"),
            content_min_length=_coerce_int(raw_env.get("CONTENT_MIN_LENGTH"), default=10, minimum=1, maximum=280, name="CONTENT_MIN_LENGTH"),
            content_max_length=_coerce_int(raw_env.get("CONTENT_MAX_LENGTH"), default=280, minimum=10, maximum=280, name="CONTENT_MAX_LENGTH"),
            enable_manual_review=_coerce_bool(raw_env.get("ENABLE_MANUAL_REVIEW"), default=False),
        )

        accounts: List[XAccount] = []
        for index in range(1, 11):
            username = raw_env.get(f"X_ACCOUNT_{index}_USERNAME", "").strip()
            password = raw_env.get(f"X_ACCOUNT_{index}_PASSWORD", "").strip()
            if username and password:
                accounts.append(XAccount(username=username, password=password))
            elif username and not password:
                LOGGER.warning(
                    "Password missing for X account %s. Skipping this credential pair.",
                    username,
                )

        return cls(
            database_url=database_url,
            redis_url=redis_url,
            perplexity_api_key=perplexity_api_key,
            perplexity_model=perplexity_model,
            posts_per_hour=posts_per_hour,
            daily_post_cap=daily_post_cap,
            app_env=app_env,
            log_level=log_level,
            playwright_headless=playwright_headless,
            rate_limit=rate_limit,
            safety=safety,
            x_accounts=accounts,
        )


def _coerce_int(value: Optional[str], *, default: int, minimum: int, maximum: int, name: str) -> int:
    if value is None or value.strip() == "":
        return default
    try:
        numeric = int(value)
    except ValueError as exc:  # pragma: no cover - defensive
        raise ValueError(f"{name} must be an integer") from exc
    if not (minimum <= numeric <= maximum):
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return numeric


def _coerce_float(value: Optional[str], *, default: float, minimum: float, maximum: float, name: str) -> float:
    if value is None or value.strip() == "":
        return default
    try:
        number = float(value)
    except ValueError as exc:  # pragma: no cover - defensive
        raise ValueError(f"{name} must be a float") from exc
    if not (minimum <= number <= maximum):
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return number


def _coerce_bool(value: Optional[str], *, default: bool) -> bool:
    if value is None or value.strip() == "":
        return default
    return value.lower() in {"1", "true", "yes", "on"}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings.from_env()
    LOGGER.debug(
        "Settings loaded (env=%s, accounts=%d)",
        settings.app_env,
        len(settings.x_accounts),
    )
    return settings


def reload_settings() -> Settings:
    get_settings.cache_clear()
    return get_settings()


def _resolve_path(path: Optional[str | Path], default: Path) -> Path:
    if path is None:
        return default
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = PROJECT_ROOT / candidate
    return candidate


@lru_cache(maxsize=1)
def load_targets_config(path: Optional[str | Path] = None) -> TargetsConfig:
    config_path = _resolve_path(path, DEFAULT_TARGETS_PATH)
    if not config_path.exists():
        raise FileNotFoundError(f"Targets configuration not found at {config_path}")

    raw_lines = config_path.read_text(encoding="utf-8").splitlines()
    sanitized = "\n".join(line for line in raw_lines if not line.lstrip().startswith("//"))

    try:
        payload = json.loads(sanitized)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {config_path}: {exc}") from exc

    engagement_raw = payload.get("engagement_threshold", {})
    engagement = EngagementThreshold(
        min_likes=int(engagement_raw.get("min_likes", 0)),
        min_retweets=int(engagement_raw.get("min_retweets", 0)),
    )

    def _clean_list(items: Sequence[str]) -> List[str]:
        return [item.strip() for item in items if isinstance(item, str) and item.strip()]

    return TargetsConfig(
        keywords=_clean_list(payload.get("keywords", [])),
        topic_clusters={key: _clean_list(value) for key, value in (payload.get("topic_clusters") or {}).items()},
        hashtags=_clean_list(payload.get("hashtags", [])),
        languages=_clean_list(payload.get("languages", ["en"])),
        sources=_clean_list(payload.get("sources", [])),
        content_types=_clean_list(payload.get("content_types", [])),
        time_window_days=int(payload.get("time_window_days", 1)),
        engagement_threshold=engagement,
        exclude_keywords=_clean_list(payload.get("exclude_keywords", [])),
        exclude_users=_clean_list(payload.get("exclude_users", [])),
        strict_match_phrases=_clean_list(payload.get("strict_match_phrases", [])),
    )


def reload_targets_config(path: Optional[str | Path] = None) -> TargetsConfig:
    load_targets_config.cache_clear()
    return load_targets_config(path)


@lru_cache(maxsize=1)
def load_blocklist(path: Optional[str | Path] = None) -> Tuple[str, ...]:
    blocklist_path = _resolve_path(path, DEFAULT_BLOCKLIST_PATH)
    if not blocklist_path.exists():
        LOGGER.warning("Blocklist not found at %s. Continuing with empty list.", blocklist_path)
        return tuple()

    entries: List[str] = []
    for line in blocklist_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        entries.append(stripped.lower())

    # Preserve order while removing duplicates
    seen = dict.fromkeys(entries)
    return tuple(seen.keys())


def reload_blocklist(path: Optional[str | Path] = None) -> Tuple[str, ...]:
    load_blocklist.cache_clear()
    return load_blocklist(path)


__all__ = [
    "CONFIG_DIR",
    "DEFAULT_BLOCKLIST_PATH",
    "DEFAULT_TARGETS_PATH",
    "EngagementThreshold",
    "RateLimitSettings",
    "SafetySettings",
    "Settings",
    "TargetsConfig",
    "XAccount",
    "get_settings",
    "load_targets_config",
    "load_blocklist",
    "reload_settings",
    "reload_targets_config",
    "reload_blocklist",
]
