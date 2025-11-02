import asyncio
import json
import os
import unittest
from datetime import datetime, timezone
from typing import List, Optional
from unittest.mock import AsyncMock, patch

import httpx

from src.services.crawler import CrawlResult
from src.services.generator import (
    PERPLEXITY_ENDPOINT,
    GenerationRequest,
    ReplyGenerator,
)
from src.utils.html_parser import ParsedMedia


def make_crawl_result(
    tweet_id: str = "tweet-1",
    content: str = "Test tweet",
    media: Optional[List[ParsedMedia]] = None,
) -> CrawlResult:
    return CrawlResult(
        id=tweet_id,
        author_handle="user",
        author_display="User",
        content=content,
        url=f"https://x.com/user/status/{tweet_id}",
        likes=0,
        retweets=0,
        reply_count=0,
        bookmarks=0,
        views=0,
        tweeted_at=datetime.now(timezone.utc),
        captured_at=datetime.now(timezone.utc),
        media=media or [],
    )


class ReplyGeneratorTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.env_patch = patch.dict(
            os.environ,
            {
                "DATABASE_URL": "postgresql://user:pass@localhost:5432/db",
                "REDIS_URL": "redis://localhost:6379/0",
                "PERPLEXITY_API_KEY": "test-key",
                "PERPLEXITY_MODEL": "test-model",
                "APP_ENV": "production",
                "POSTS_PER_HOUR": "2",
                "DAILY_POST_CAP": "10",
                "PERPLEXITY_MAX_RPM": "100",
            },
            clear=True,
        )
        self.env_patch.start()

    def tearDown(self) -> None:
        self.env_patch.stop()

    async def asyncTearDown(self) -> None:
        if getattr(self, "generator", None):
            await self.generator.aclose()

    async def test_successful_generation(self):
        self.generator = ReplyGenerator()
        reply_text = "This is a thoughtful reply"
        payload = {
            "model": "test-model",
            "choices": [
                {
                    "message": {"content": reply_text},
                    "confidence": 0.87,
                }
            ],
        }
        response = httpx.Response(
            status_code=200,
            content=json.dumps(payload).encode("utf-8"),
            request=httpx.Request("POST", PERPLEXITY_ENDPOINT),
        )
        self.generator._client.post = AsyncMock(return_value=response)  # type: ignore[attr-defined]

        request = GenerationRequest(target=make_crawl_result(), media=[])
        results = await self.generator.generate([request])

        self.assertEqual(len(results), 1)
        generated = results[0]
        self.assertEqual(generated.content, reply_text)
        self.assertAlmostEqual(generated.confidence, 0.87)
        self.assertEqual(generated.model_used, "test-model")
        self.assertIsNone(generated.error)

    async def test_rate_limit_backoff_then_success(self):
        self.generator = ReplyGenerator()
        rate_limited = httpx.Response(
            status_code=429,
            request=httpx.Request("POST", PERPLEXITY_ENDPOINT),
        )
        ok_payload = {
            "model": "test-model",
            "choices": [{"message": {"content": "retry success"}, "confidence": 0.5}],
        }
        ok_response = httpx.Response(
            status_code=200,
            content=json.dumps(ok_payload).encode("utf-8"),
            request=httpx.Request("POST", PERPLEXITY_ENDPOINT),
        )
        self.generator._client.post = AsyncMock(side_effect=[rate_limited, ok_response])  # type: ignore[attr-defined]

        with patch("src.services.generator.asyncio.sleep", new=AsyncMock()) as sleep_mock:
            request = GenerationRequest(target=make_crawl_result("tweet-2"), media=[])
            results = await self.generator.generate([request])

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].content, "retry success")
        self.assertGreaterEqual(sleep_mock.await_count, 1)

    async def test_invalid_json(self):
        self.generator = ReplyGenerator()
        bad_response = httpx.Response(
            status_code=200,
            content=b"not-json",
            request=httpx.Request("POST", PERPLEXITY_ENDPOINT),
        )
        self.generator._client.post = AsyncMock(return_value=bad_response)  # type: ignore[attr-defined]

        request = GenerationRequest(target=make_crawl_result("tweet-3"), media=[])
        results = await self.generator.generate([request])

        self.assertEqual(results[0].error, "invalid_json")
        self.assertEqual(results[0].content, "")

    async def test_refusal(self):
        self.generator = ReplyGenerator()
        refusal_payload = {
            "model": "test-model",
            "choices": [{"message": {"refusal": "cannot"}}],
        }
        refusal_response = httpx.Response(
            status_code=200,
            content=json.dumps(refusal_payload).encode("utf-8"),
            request=httpx.Request("POST", PERPLEXITY_ENDPOINT),
        )
        self.generator._client.post = AsyncMock(return_value=refusal_response)  # type: ignore[attr-defined]

        request = GenerationRequest(target=make_crawl_result("tweet-4"), media=[])
        results = await self.generator.generate([request])

        self.assertEqual(results[0].error, "refused")
        self.assertEqual(results[0].content, "")

    async def test_prompt_includes_media_context(self):
        self.generator = ReplyGenerator()
        payload = {
            "model": "test-model",
            "choices": [{"message": {"content": "media"}}],
        }
        ok_response = httpx.Response(
            status_code=200,
            content=json.dumps(payload).encode("utf-8"),
            request=httpx.Request("POST", PERPLEXITY_ENDPOINT),
        )
        self.generator._client.post = AsyncMock(return_value=ok_response)  # type: ignore[attr-defined]

        media_target = make_crawl_result(
            "tweet-5",
            media=[ParsedMedia(kind="photo", url="https://example.com/img.jpg", alt_text="Sample image")],
        )

        with patch.object(self.generator, "_respect_rate_limit", new=AsyncMock()):
            request = GenerationRequest(target=media_target, media=media_target.media)
            await self.generator.generate([request])

        called_payload = self.generator._client.post.call_args.kwargs["json"]  # type: ignore[attr-defined]
        user_message = called_payload["messages"][1]["content"]
        self.assertIn("Media context", user_message)
        self.assertIn("Sample image", user_message)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
