import unittest
from pathlib import Path

from src.utils.html_parser import extract_tweets_from_html


fixture_dir = Path(__file__).resolve().parent / "fixtures"
PLAIN_TWEET = (fixture_dir / "x_tweet.html").read_text(encoding="utf-8")
IMAGE_TWEET = (fixture_dir / "x_tweet_image.html").read_text(encoding="utf-8")


class HtmlParserTests(unittest.TestCase):
    def test_extract_single_tweet(self):
        tweets = extract_tweets_from_html(PLAIN_TWEET)
        self.assertEqual(len(tweets), 1)
        tweet = tweets[0]
        self.assertEqual(tweet.tweet_id, "1984649802517283174")
        self.assertEqual(tweet.author_handle, "shydev69")
        self.assertEqual(tweet.author_display, "shydev.eth")
        self.assertIn("I made $9684.37", tweet.text)
        self.assertEqual(tweet.replies, 44)
        self.assertEqual(tweet.reposts, 4)
        self.assertEqual(tweet.likes, 224)
        self.assertEqual(tweet.bookmarks, 24)
        self.assertEqual(tweet.views, 7451)
        self.assertEqual(tweet.permalink, "https://x.com/shydev69/status/1984649802517283174")
        self.assertEqual(tweet.timestamp.isoformat(), "2025-11-01T15:52:40+00:00")
        self.assertEqual(len(tweet.media), 0)

    def test_extract_tweet_with_media(self):
        tweets = extract_tweets_from_html(IMAGE_TWEET)
        self.assertEqual(len(tweets), 1)
        tweet = tweets[0]
        self.assertEqual(tweet.tweet_id, "1984315375060918746")
        self.assertEqual(len(tweet.media), 1)
        media = tweet.media[0]
        self.assertEqual(media.kind, "photo")
        self.assertEqual(media.url, "https://pbs.twimg.com/media/G4m0UMWWYAAif5E?format=jpg&name=small")
        self.assertEqual(media.alt_text, "Dashboard screenshot")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
