import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.utils import config as config_utils


class ConfigUtilsTests(unittest.TestCase):
    def tearDown(self) -> None:
        config_utils.get_settings.cache_clear()
        config_utils.load_targets_config.cache_clear()
        config_utils.load_blocklist.cache_clear()

    @patch.dict(
        os.environ,
        {
            "DATABASE_URL": "postgresql://user:pass@localhost:5432/db",
            "REDIS_URL": "redis://localhost:6379/0",
            "PERPLEXITY_API_KEY": "valid-key",
            "PERPLEXITY_MODEL": "model-x",
            "APP_ENV": "development",
            "POSTS_PER_HOUR": "3",
            "DAILY_POST_CAP": "12",
            "X_ACCOUNT_1_USERNAME": "user1",
            "X_ACCOUNT_1_PASSWORD": "pass1",
            "X_ACCOUNT_2_USERNAME": "user2",
        },
        clear=True,
    )
    def test_settings_loading_and_validation(self):
        settings = config_utils.reload_settings()

        self.assertEqual(settings.database_url, "postgresql://user:pass@localhost:5432/db")
        self.assertEqual(settings.redis_url, "redis://localhost:6379/0")
        self.assertEqual(settings.perplexity_api_key, "valid-key")
        self.assertEqual(settings.app_env, "development")
        self.assertEqual(settings.log_level, "DEBUG")
        self.assertFalse(settings.playwright_headless)
        self.assertEqual(settings.posts_per_hour, 3)
        self.assertEqual(settings.daily_post_cap, 12)
        self.assertEqual(len(settings.x_accounts), 1)
        self.assertEqual(settings.x_accounts[0].username, "user1")

    @patch.dict(
        os.environ,
        {
            "DATABASE_URL": "http://invalid",
            "REDIS_URL": "redis://localhost:6379/0",
            "PERPLEXITY_API_KEY": "valid-key",
        },
        clear=True,
    )
    def test_settings_invalid_database_url(self):
        with self.assertRaises(ValueError):
            config_utils.reload_settings()

    def test_load_targets_config_with_comments(self):
        data = {
            "keywords": ["AI"],
            "topic_clusters": {"agents": ["autonomous agents"]},
            "hashtags": ["#AI"],
            "languages": ["en"],
            "sources": ["forums"],
            "content_types": ["tweet"],
            "time_window_days": 3,
            "engagement_threshold": {"min_likes": 1, "min_retweets": 0},
            "exclude_keywords": ["politics"],
            "exclude_users": [],
            "strict_match_phrases": ["autonomous agent"],
        }

        with tempfile.NamedTemporaryFile("w", delete=False) as tmp:
            tmp.write("// comment\n")
            json.dump(data, tmp)
            tmp.flush()
            path = Path(tmp.name)

        try:
            config_utils.reload_targets_config(path)
            targets = config_utils.load_targets_config(path)
            self.assertEqual(targets.keywords, ["AI"])
            self.assertEqual(targets.topic_clusters["agents"], ["autonomous agents"])
        finally:
            path.unlink(missing_ok=True)

    def test_load_blocklist(self):
        content = """# heading
politics
Politics

spam
"""
        with tempfile.NamedTemporaryFile("w", delete=False) as tmp:
            tmp.write(content)
            tmp.flush()
            path = Path(tmp.name)

        try:
            config_utils.reload_blocklist(path)
            blocklist = config_utils.load_blocklist(path)
            self.assertEqual(blocklist, ("politics", "spam"))
        finally:
            path.unlink(missing_ok=True)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
