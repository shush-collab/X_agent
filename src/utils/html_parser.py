"""HTML parsing utilities for extracting tweets from X timelines."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

BASE_URL = "https://x.com"


@dataclass(frozen=True)
class ParsedTweet:
    tweet_id: str
    author_handle: str
    author_display: str
    text: str
    permalink: str
    replies: int
    reposts: int
    likes: int
    bookmarks: int
    views: int
    timestamp: datetime
    media: List["ParsedMedia"]


@dataclass(frozen=True)
class ParsedMedia:
    kind: str
    url: str
    alt_text: str


_METRIC_KEYS: Dict[str, str] = {
    "repl": "replies",
    "reply": "replies",
    "replies": "replies",
    "repost": "reposts",
    "reposts": "reposts",
    "retweet": "reposts",
    "retweets": "reposts",
    "like": "likes",
    "likes": "likes",
    "bookmark": "bookmarks",
    "bookmarks": "bookmarks",
    "view": "views",
    "views": "views",
}


def extract_tweets_from_html(html: str, base_url: str = BASE_URL) -> List[ParsedTweet]:
    """Parse the supplied HTML and return a list of tweets."""

    soup = BeautifulSoup(html, "html.parser")
    articles = soup.select("article[data-testid='tweet']")
    tweets: List[ParsedTweet] = []
    for article in articles:
        try:
            parsed = _parse_single_tweet(article, base_url)
        except ValueError:
            continue
        tweets.append(parsed)
    return tweets


def _parse_single_tweet(article, base_url: str) -> ParsedTweet:
    header = article.select_one("[data-testid='User-Name'] a[href^='/']")
    if header is None:
        raise ValueError("missing user header")
    author_display = header.get_text(strip=True)
    author_handle = header.get("href", "").strip().lstrip("/")
    if not author_handle:
        raise ValueError("missing author handle")

    permalink_anchor = article.select_one("a[href*='/status/'] time")
    if permalink_anchor is None:
        raise ValueError("missing timestamp anchor")
    time_tag = permalink_anchor
    permalink_href = time_tag.parent.get("href", "") if time_tag.parent else ""
    if not permalink_href:
        raise ValueError("missing permalink")
    permalink = urljoin(base_url, permalink_href)
    tweet_id = permalink_href.split("status/")[-1]
    tweet_id = tweet_id.split("?")[0]

    timestamp_raw = time_tag.get("datetime")
    timestamp = _parse_timestamp(timestamp_raw)

    text_block = article.select_one("[data-testid='tweetText']")
    text = text_block.get_text(" ", strip=True) if text_block else ""

    metrics_group = article.select_one("div[aria-label][role='group']")
    metrics = _parse_metrics(metrics_group.get("aria-label") if metrics_group else "")
    media = _parse_media(article)

    return ParsedTweet(
        tweet_id=tweet_id,
        author_handle=author_handle,
        author_display=author_display,
        text=text,
        permalink=permalink,
        replies=metrics.get("replies", 0),
        reposts=metrics.get("reposts", 0),
        likes=metrics.get("likes", 0),
        bookmarks=metrics.get("bookmarks", 0),
        views=metrics.get("views", 0),
        timestamp=timestamp,
        media=media,
    )


def _parse_timestamp(value: Optional[str]) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    cleaned = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(cleaned)
    except ValueError:
        return datetime.now(timezone.utc)


def _parse_metrics(label: Optional[str]) -> Dict[str, int]:
    metrics: Dict[str, int] = {"replies": 0, "reposts": 0, "likes": 0, "bookmarks": 0, "views": 0}
    if not label:
        return metrics

    parts = [part.strip() for part in label.split(",") if part.strip()]
    for part in parts:
        tokens = part.split()
        if not tokens:
            continue
        count_raw = tokens[0]
        descriptor = tokens[-1].lower()
        key = None
        for prefix, metric_key in _METRIC_KEYS.items():
            if descriptor.startswith(prefix):
                key = metric_key
                break
        if key is None:
            continue
        metrics[key] = _parse_count(count_raw)
    return metrics


def _parse_count(value: str) -> int:
    cleaned = value.replace(",", "").strip().lower()
    if cleaned.endswith("k"):
        return int(float(cleaned[:-1]) * 1_000)
    if cleaned.endswith("m"):
        return int(float(cleaned[:-1]) * 1_000_000)
    if cleaned.endswith("b"):
        return int(float(cleaned[:-1]) * 1_000_000_000)
    try:
        return int(float(cleaned))
    except ValueError:
        return 0


def _parse_media(article) -> List[ParsedMedia]:
    media: List[ParsedMedia] = []
    photo_nodes = article.select("[data-testid='tweetPhoto']")
    for node in photo_nodes:
        img = node.find("img")
        alt_text = ""
        src = ""
        if img and img.get("src"):
            src = img.get("src").strip()
            alt_text = (img.get("alt") or "").strip()
        else:
            style = node.get("style", "")
            if "background-image" in style:
                segment = style.split("background-image")[-1]
                if "url" in segment:
                    src = segment.split("url(", 1)[-1].split(")", 1)[0].strip('"\' ')
        if src:
            media.append(ParsedMedia(kind="photo", url=src, alt_text=alt_text))
    return media


__all__ = [
    "ParsedTweet",
    "ParsedMedia",
    "extract_tweets_from_html",
]
