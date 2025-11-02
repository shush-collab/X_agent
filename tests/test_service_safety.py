import os
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from src.services.generator import GeneratedReply
from src.services.safety import SafetyFilter


def make_reply(content: str, **overrides) -> GeneratedReply:
    return GeneratedReply(
        id=overrides.get("id", "tweet-1"),
        content=content,
        confidence=overrides.get("confidence", 0.9),
        model_used="test-model",
        generated_at=datetime.now(timezone.utc),
        error=overrides.get("error"),
    )


class SafetyFilterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env_patch = patch.dict(
            os.environ,
            {
                "DATABASE_URL": "postgresql://user:pass@localhost:5432/db",
                "REDIS_URL": "redis://localhost:6379/0",
                "PERPLEXITY_API_KEY": "test-key",
                "APP_ENV": "production",
                "POSTS_PER_HOUR": "2",
                "DAILY_POST_CAP": "10",
            },
            clear=True,
        )
        self.env_patch.start()

    def tearDown(self) -> None:
        self.env_patch.stop()

    def test_approve_clean_reply(self):
        filter_ = SafetyFilter()
        decision = filter_.evaluate([make_reply("A thoughtful response with enough detail and insight.")])[0]
        self.assertTrue(decision.approved)
        self.assertIsNone(decision.reason)

    def test_blocklist_rejection(self):
        filter_ = SafetyFilter()
        decision = filter_.evaluate([make_reply("Avoid politics please")])[0]
        self.assertFalse(decision.approved)
        self.assertIn("blocked_term", decision.reason)

    def test_length_checks(self):
        filter_ = SafetyFilter()
        short_decision = filter_.evaluate([make_reply("Hi")])[0]
        self.assertFalse(short_decision.approved)
        self.assertEqual(short_decision.reason, "too_short")

        long_content = "L" * (filter_._settings.safety.content_max_length + 1)  # type: ignore[attr-defined]
        long_decision = filter_.evaluate([make_reply(long_content)])[0]
        self.assertFalse(long_decision.approved)
        self.assertEqual(long_decision.reason, "too_long")

    def test_manual_review_enabled(self):
        from src.utils import config as config_utils

        config_utils.get_settings.cache_clear()
        with patch.dict(os.environ, {"ENABLE_MANUAL_REVIEW": "true", "MANUAL_REVIEW_THRESHOLD": "0.95"}, clear=False):
            config_utils.get_settings.cache_clear()
            filter_ = SafetyFilter()

        decision = filter_.evaluate([make_reply("Solid reply with enough detail", confidence=0.5, id="tweet-low")])[0]
        self.assertFalse(decision.approved)
        self.assertEqual(decision.reason, "manual_review")

    def test_generation_error(self):
        filter_ = SafetyFilter()
        decision = filter_.evaluate([make_reply("", error="timeout")])[0]
        self.assertFalse(decision.approved)
        self.assertEqual(decision.reason, "generation_error:timeout")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
