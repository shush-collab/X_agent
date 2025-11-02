import asyncio
import os
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from src.services import crawler as crawler_service
from src.utils import config as config_utils


fixture_dir = Path(__file__).resolve().parent / "fixtures"
PLAIN_HTML = (fixture_dir / "x_tweet.html").read_text(encoding="utf-8")
IMAGE_HTML = (fixture_dir / "x_tweet_image.html").read_text(encoding="utf-8")


class CrawlerServiceTests(unittest.TestCase):
    def tearDown(self) -> None:
        config_utils.get_settings.cache_clear()
        config_utils.load_targets_config.cache_clear()
        config_utils.load_blocklist.cache_clear()
        crawler_service._CRAWLER = None  # type: ignore[attr-defined]

    @patch.dict(
        os.environ,
        {
            "DATABASE_URL": "postgresql://user:pass@localhost:5432/db",
            "REDIS_URL": "redis://localhost:6379/0",
            "PERPLEXITY_API_KEY": "valid-key",
            "APP_ENV": "development",
            "POSTS_PER_HOUR": "2",
            "DAILY_POST_CAP": "10",
        },
        clear=True,
    )
    def test_fetch_fragments_parses_real_html(self):
        config_utils.reload_settings()
        config_utils.reload_targets_config()

        mock_html = AsyncMock(return_value=PLAIN_HTML)

        with patch.object(crawler_service.Crawler, "_collect_html", new=mock_html):
            results = asyncio.run(crawler_service.fetch_fragments())

        self.assertEqual(len(results), 1)
        result = results[0]
        self.assertIsInstance(result, crawler_service.CrawlResult)
        self.assertEqual(result.id, "1984649802517283174")
        self.assertEqual(result.author_handle, "shydev69")
        self.assertEqual(result.author_display, "shydev.eth")
        self.assertEqual(result.likes, 224)
        self.assertEqual(result.retweets, 4)
        self.assertEqual(result.reply_count, 44)
        self.assertEqual(result.bookmarks, 24)
        self.assertEqual(result.views, 7451)
        self.assertTrue(result.content.startswith("I made $9684.37"))
        self.assertEqual(result.url, "https://x.com/shydev69/status/1984649802517283174")
        self.assertEqual(result.tweeted_at.isoformat(), "2025-11-01T15:52:40+00:00")
        self.assertGreaterEqual(result.captured_at, result.tweeted_at)
        self.assertEqual(len(result.media), 0)

    @patch.dict(
        os.environ,
        {
            "DATABASE_URL": "postgresql://user:pass@localhost:5432/db",
            "REDIS_URL": "redis://localhost:6379/0",
            "PERPLEXITY_API_KEY": "valid-key",
            "POSTS_PER_HOUR": "2",
            "DAILY_POST_CAP": "10",
        },
        clear=True,
    )
    def test_fetch_fragments_handles_media(self):
        config_utils.reload_settings()
        config_utils.reload_targets_config()

        mock_html = AsyncMock(return_value=IMAGE_HTML)

        with patch.object(crawler_service.Crawler, "_collect_html", new=mock_html):
            results = asyncio.run(crawler_service.fetch_fragments())

        self.assertEqual(len(results), 1)
        result = results[0]
        self.assertEqual(result.id, "1984315375060918746")
        self.assertEqual(len(result.media), 1)
        media = result.media[0]
        self.assertEqual(media.kind, "photo")
        self.assertEqual(media.url, "https://pbs.twimg.com/media/G4m0UMWWYAAif5E?format=jpg&name=small")
        self.assertEqual(media.alt_text, "Dashboard screenshot")

    @patch.dict(
        os.environ,
        {
            "DATABASE_URL": "postgresql://user:pass@localhost:5432/db",
            "REDIS_URL": "redis://localhost:6379/0",
            "PERPLEXITY_API_KEY": "valid-key",
            "CRAWL_COOLDOWN_MINUTES": "1",
            "POSTS_PER_HOUR": "2",
            "DAILY_POST_CAP": "10",
        },
        clear=True,
    )
    def test_cooldown_prevents_back_to_back_runs(self):
        config_utils.reload_settings()
        config_utils.reload_targets_config()

        mock_html = AsyncMock(return_value=PLAIN_HTML)

        with patch.object(crawler_service.Crawler, "_collect_html", new=mock_html):
            crawler = crawler_service.get_crawler()
            asyncio.run(crawler.fetch())
            with self.assertRaises(RuntimeError):
                asyncio.run(crawler.fetch())

    @patch("src.services.crawler.async_playwright")
    @patch("src.services.crawler.get_settings")
    def test_collect_html_uses_storage_state(self, get_settings_mock, async_playwright_mock):
        get_settings_mock.return_value = SimpleNamespace(playwright_headless=True, rate_limit=SimpleNamespace(crawl_cooldown_minutes=0))

        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        storage_path = Path(temp_dir.name) / "x_storage.json"
        storage_path.write_text(json.dumps({"cookies": []}))

        original_config_dir = crawler_service.CONFIG_DIR
        crawler_service.CONFIG_DIR = Path(temp_dir.name)
        self.addCleanup(lambda: setattr(crawler_service, "CONFIG_DIR", original_config_dir))

        page_mock = SimpleNamespace(
            goto=AsyncMock(),
            wait_for_selector=AsyncMock(),
            content=AsyncMock(return_value="<html></html>"),
        )
        context_mock = SimpleNamespace(
            new_page=AsyncMock(return_value=page_mock),
            close=AsyncMock(),
        )
        browser_mock = SimpleNamespace(
            new_context=AsyncMock(return_value=context_mock),
            close=AsyncMock(),
        )

        class DummyPlaywright:
            def __init__(self, browser):
                self.chromium = SimpleNamespace(launch=AsyncMock(return_value=browser))

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

        async_playwright_mock.return_value = DummyPlaywright(browser_mock)

        crawler = crawler_service.Crawler()
        result = asyncio.run(crawler._collect_html(crawler_service.CrawlQuery()))

        self.assertEqual(result, "<html></html>")
        browser_mock.new_context.assert_awaited_once()
        kwargs = browser_mock.new_context.await_args.kwargs
        self.assertEqual(kwargs.get("storage_state"), str(storage_path))

    @patch("src.services.crawler.get_settings")
    def test_launch_browser_retries_without_sandbox(self, get_settings_mock):
        get_settings_mock.return_value = SimpleNamespace(playwright_headless=True, rate_limit=SimpleNamespace(crawl_cooldown_minutes=0))
        crawler = crawler_service.Crawler()

        sandbox_error = RuntimeError("Check failed: sandbox error")
        browser_mock = object()

        launch_mock = AsyncMock(side_effect=[sandbox_error, browser_mock])
        firefox_launch_mock = AsyncMock()
        playwright = SimpleNamespace(
            chromium=SimpleNamespace(launch=launch_mock),
            firefox=SimpleNamespace(launch=firefox_launch_mock),
        )

        result = asyncio.run(crawler._launch_browser(playwright))

        self.assertIs(result, browser_mock)
        self.assertEqual(launch_mock.await_count, 2)
        firefox_launch_mock.assert_not_called()
        first_call = launch_mock.await_args_list[0]
        second_call = launch_mock.await_args_list[1]
        self.assertEqual(first_call.kwargs, {"headless": True})
        self.assertEqual(
            second_call.kwargs,
            {
                "headless": True,
                "chromium_sandbox": False,
                "args": ["--no-sandbox", "--disable-dev-shm-usage", "--disable-setuid-sandbox"],
            },
        )

    @patch("src.services.crawler.get_settings")
    def test_launch_browser_falls_back_to_firefox(self, get_settings_mock):
        get_settings_mock.return_value = SimpleNamespace(playwright_headless=True, rate_limit=SimpleNamespace(crawl_cooldown_minutes=0))
        crawler = crawler_service.Crawler()

        sandbox_error = RuntimeError("Check failed: sandbox error")
        chromium_launch_mock = AsyncMock(side_effect=[sandbox_error, sandbox_error, sandbox_error])
        firefox_browser = object()
        firefox_launch_mock = AsyncMock(return_value=firefox_browser)
        playwright = SimpleNamespace(
            chromium=SimpleNamespace(launch=chromium_launch_mock),
            firefox=SimpleNamespace(launch=firefox_launch_mock),
        )

        result = asyncio.run(crawler._launch_browser(playwright))

        self.assertIs(result, firefox_browser)
        self.assertEqual(chromium_launch_mock.await_count, 3)
        firefox_launch_mock.assert_awaited_once_with(headless=True)

    @patch("src.services.crawler.get_settings")
    def test_launch_browser_uses_chrome_channel_fallback(self, get_settings_mock):
        get_settings_mock.return_value = SimpleNamespace(playwright_headless=False, rate_limit=SimpleNamespace(crawl_cooldown_minutes=0))
        crawler = crawler_service.Crawler()

        sandbox_error = RuntimeError("Check failed: sandbox error")
        chrome_browser = object()
        chromium_launch_mock = AsyncMock(side_effect=[sandbox_error, sandbox_error, chrome_browser])
        firefox_launch_mock = AsyncMock()
        playwright = SimpleNamespace(
            chromium=SimpleNamespace(launch=chromium_launch_mock),
            firefox=SimpleNamespace(launch=firefox_launch_mock),
        )

        result = asyncio.run(crawler._launch_browser(playwright))

        self.assertIs(result, chrome_browser)
        self.assertEqual(chromium_launch_mock.await_count, 3)
        firefox_launch_mock.assert_not_called()
        first_call, second_call, third_call = chromium_launch_mock.await_args_list
        self.assertEqual(first_call.kwargs, {"headless": False})
        self.assertEqual(
            second_call.kwargs,
            {
                "headless": False,
                "chromium_sandbox": False,
                "args": ["--no-sandbox", "--disable-dev-shm-usage", "--disable-setuid-sandbox"],
            },
        )
        self.assertEqual(
            third_call.kwargs,
            {
                "headless": False,
                "channel": "chrome",
                "args": ["--no-sandbox", "--disable-dev-shm-usage", "--disable-setuid-sandbox"],
            },
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
