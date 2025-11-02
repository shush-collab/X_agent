"""Crawler service for discovering content on X."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from urllib.parse import quote_plus, urlencode

from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright

from src.utils.config import CONFIG_DIR, get_settings, load_targets_config
from src.utils.html_parser import ParsedMedia, ParsedTweet, extract_tweets_from_html
from src.utils.logger import get_logger, set_correlation_id

LOGGER = get_logger("services.crawler")


@dataclass(frozen=True)
class CrawlQuery:
    keywords: List[str] = field(default_factory=list)
    hashtags: List[str] = field(default_factory=list)
    sources: List[str] = field(default_factory=list)
    languages: List[str] = field(default_factory=list)
    exclude_keywords: List[str] = field(default_factory=list)
    strict_phrases: List[str] = field(default_factory=list)
    time_window_days: int = 1


@dataclass(frozen=True)
class CrawlResult:
    id: str
    author_handle: str
    author_display: str
    content: str
    url: str
    likes: int
    retweets: int
    reply_count: int
    bookmarks: int
    views: int
    tweeted_at: datetime
    captured_at: datetime
    media: List[ParsedMedia]


class Crawler:
    """Discovers relevant X content matching configured targets."""

    def __init__(self) -> None:
        self._settings = get_settings()
        self._last_run_at: Optional[datetime] = None

    def _enforce_cooldown(self) -> None:
        cooldown_minutes = self._settings.rate_limit.crawl_cooldown_minutes
        if self._last_run_at is None:
            return
        next_allowed = self._last_run_at + timedelta(minutes=cooldown_minutes)
        if datetime.utcnow() < next_allowed:
            raise RuntimeError("Crawler cooldown active. Try again later.")

    def _update_last_run(self) -> None:
        self._last_run_at = datetime.utcnow()

    def _build_query(self, query: Optional[CrawlQuery]) -> CrawlQuery:
        if query is not None:
            return query
        targets = load_targets_config()
        return CrawlQuery(
            keywords=list(targets.keywords),
            hashtags=list(targets.hashtags),
            sources=list(targets.sources),
            languages=list(targets.languages),
            exclude_keywords=list(targets.exclude_keywords),
            strict_phrases=list(targets.strict_match_phrases),
            time_window_days=targets.time_window_days,
        )

    async def fetch(self, query: Optional[CrawlQuery] = None) -> List[CrawlResult]:
        self._enforce_cooldown()
        correlation_id = f"crawl-{datetime.utcnow().isoformat()}"
        set_correlation_id(correlation_id)

        prepared_query = self._build_query(query)
        LOGGER.info(
            "Starting crawl",
            extra={
                "keywords": prepared_query.keywords,
                "hashtags": prepared_query.hashtags,
                "sources": prepared_query.sources,
            },
        )

        try:
            html = await self._collect_html(prepared_query)
        except Exception as exc:
            LOGGER.error("Crawler failed", extra={"error": type(exc).__name__, "detail": str(exc)})
            raise

        parsed = extract_tweets_from_html(html)
        results = [self._convert_parsed(tweet) for tweet in parsed]

        LOGGER.info("Crawl complete", extra={"count": len(results)})
        self._update_last_run()
        return results

    def _convert_parsed(self, tweet: ParsedTweet) -> CrawlResult:
        now = datetime.now(timezone.utc)
        return CrawlResult(
            id=tweet.tweet_id,
            author_handle=tweet.author_handle,
            author_display=tweet.author_display,
            content=tweet.text,
            url=tweet.permalink,
            likes=tweet.likes,
            retweets=tweet.reposts,
            reply_count=tweet.replies,
            bookmarks=tweet.bookmarks,
            views=tweet.views,
            tweeted_at=tweet.timestamp,
            captured_at=now,
            media=tweet.media,
        )

    def _build_search_url(self, query: CrawlQuery) -> str:
        terms: List[str] = []

        for phrase in query.strict_phrases:
            phrase_clean = phrase.strip()
            if phrase_clean:
                terms.append(_quote_term(phrase_clean, wrap_quotes=True))

        for keyword in query.keywords:
            keyword_clean = keyword.strip()
            if keyword_clean:
                wrap = " " in keyword_clean
                terms.append(_quote_term(keyword_clean, wrap_quotes=wrap))

        for tag in query.hashtags:
            tag_clean = tag.strip()
            if not tag_clean:
                continue
            if not tag_clean.startswith("#"):
                tag_clean = f"#{tag_clean}"
            terms.append(tag_clean)

        if not terms:
            terms.append("AI")

        lang_filters = [lang.strip() for lang in query.languages if lang.strip()]
        if lang_filters:
            terms.append(f"lang:{lang_filters[0]}")

        expression = " OR ".join(terms)

        exclude_parts: List[str] = []
        for word in query.exclude_keywords:
            word_clean = word.strip()
            if not word_clean:
                continue
            wrap = " " in word_clean
            exclude_parts.append(f"-{_quote_term(word_clean, wrap_quotes=wrap)}")

        if exclude_parts:
            expression = f"{expression} {' '.join(exclude_parts)}"

        params = {
            "q": expression,
            "src": "typed_query",
            "f": "live",
        }
        return f"https://x.com/search?{urlencode(params, quote_via=quote_plus)}"

    async def _collect_html(self, query: CrawlQuery) -> str:
        url = self._build_search_url(query)
        LOGGER.debug("Fetching timeline", extra={"url": url})
        async with async_playwright() as playwright:
            browser = await self._launch_browser(playwright)
            storage_state_path = CONFIG_DIR / "x_storage.json"
            storage_state = str(storage_state_path) if storage_state_path.exists() else None
            context = await browser.new_context(storage_state=storage_state)
            page = await context.new_page()
            await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            try:
                await page.wait_for_selector("article[data-testid='tweet']", timeout=15_000)
            except PlaywrightTimeoutError:
                LOGGER.warning("No tweets found before timeout", extra={"url": url})
            html = await page.content()
            await context.close()
            await browser.close()
        return html

    async def _launch_browser(self, playwright) -> "Browser":
        launch_kwargs = {"headless": self._settings.playwright_headless}
        try:
            return await playwright.chromium.launch(**launch_kwargs)
        except Exception as exc:
            if not self._is_sandbox_error(exc):
                raise
            return await self._launch_chromium_without_sandbox(playwright, launch_kwargs, exc)

    async def _launch_chromium_without_sandbox(self, playwright, launch_kwargs: dict, exc: Exception):
        LOGGER.warning(
            "Chromium sandbox failed, retrying without sandbox",
            extra={"error": type(exc).__name__},
        )
        sandbox_args = ["--no-sandbox", "--disable-dev-shm-usage", "--disable-setuid-sandbox"]
        sandbox_kwargs = {
            **launch_kwargs,
            "chromium_sandbox": False,
            "args": sandbox_args,
        }
        try:
            return await playwright.chromium.launch(**sandbox_kwargs)
        except Exception as retry_exc:
            LOGGER.error(
                "Chromium launch failed even after disabling sandbox",
                extra={"error": type(retry_exc).__name__},
            )
            return await self._launch_chrome_channel(playwright, launch_kwargs)

    async def _launch_chrome_channel(self, playwright, launch_kwargs: dict):
        chrome_args = ["--no-sandbox", "--disable-dev-shm-usage", "--disable-setuid-sandbox"]
        chrome_kwargs = {
            **launch_kwargs,
            "channel": "chrome",
            "args": chrome_args,
        }
        LOGGER.warning(
            "Retrying Playwright launch via system Chrome channel",
            extra={"headless": launch_kwargs.get("headless", True)},
        )
        try:
            return await playwright.chromium.launch(**chrome_kwargs)
        except Exception as chrome_exc:
            LOGGER.error(
                "Chrome channel launch failed",
                extra={"error": type(chrome_exc).__name__},
            )
            return await self._launch_firefox(playwright, launch_kwargs, chrome_exc)

    async def _launch_firefox(self, playwright, launch_kwargs: dict, previous_exc: Optional[Exception] = None):
        LOGGER.warning(
            "Falling back to Firefox launcher",
            extra={"headless": launch_kwargs.get("headless", True)},
        )
        try:
            return await playwright.firefox.launch(headless=launch_kwargs.get("headless", True))
        except Exception as firefox_exc:
            LOGGER.error(
                "Firefox launch failed",
                extra={"error": type(firefox_exc).__name__},
            )
            raise RuntimeError(
                "Playwright browser launch failed. Install system dependencies (`playwright install-deps`) "
                "or configure PLAYWRIGHT_BROWSERS_PATH to use an existing browser."
            ) from (previous_exc or firefox_exc)

    @staticmethod
    def _is_sandbox_error(exc: Exception) -> bool:
        message = str(exc).lower()
        return "sandbox" in message or "check failed" in message


_CRAWLER: Optional[Crawler] = None


def get_crawler() -> Crawler:
    global _CRAWLER
    if _CRAWLER is None:
        _CRAWLER = Crawler()
    return _CRAWLER


async def fetch_fragments(query: Optional[CrawlQuery] = None) -> List[CrawlResult]:
    crawler = get_crawler()
    return await crawler.fetch(query)


def run(query: Optional[CrawlQuery] = None) -> List[CrawlResult]:
    return asyncio.run(fetch_fragments(query))


def _quote_term(term: str, wrap_quotes: bool) -> str:
    cleaned = term.strip()
    if wrap_quotes and cleaned:
        if not (cleaned.startswith('"') and cleaned.endswith('"')):
            return f'"{cleaned}"'
    return cleaned


__all__ = [
    "CrawlQuery",
    "CrawlResult",
    "Crawler",
    "fetch_fragments",
    "get_crawler",
    "run",
]
