# GOAL: Manual verification of the complete workflow
# PURPOSE: Development debugging and system health checking
# RESPONSIBILITY: Test crawl → generate → post cycle with real data

"""Ad-hoc pipeline test harness for the X automation stack."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Sequence

PipelinePayload = Dict[str, Any]


LOGGER = logging.getLogger("x_automation.test_pipeline")


def _load_dotenv(env_path: Path) -> None:
    try:
        from dotenv import load_dotenv
    except ImportError as exc:  # pragma: no cover - defensive guard
        raise SystemExit(
            "python-dotenv is required for test_pipeline. Install dependencies first."
        ) from exc

    if env_path.exists():
        load_dotenv(env_path)
        LOGGER.info("Environment variables loaded from %s", env_path)
    else:
        LOGGER.warning(
            "Environment file %s not found. Falling back to system environment.", env_path
        )


def _load_targets_config(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise SystemExit(f"targets configuration missing at {path}")

    # Strip leading comment lines so the JSON can be parsed.
    filtered_lines = [
        line for line in path.read_text(encoding="utf-8").splitlines() if not line.strip().startswith("//")
    ]
    try:
        return json.loads("\n".join(filtered_lines))
    except json.JSONDecodeError as exc:
        raise SystemExit(
            f"Unable to parse targets.json. Ensure it is valid JSON without trailing commas. ({exc})"
        ) from exc


def _load_blocklist(path: Path) -> Sequence[str]:
    if not path.exists():
        LOGGER.warning("Blocklist file %s not found. Continuing with empty list.", path)
        return []
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


@dataclass
class PipelineResult:
    crawled: Sequence[PipelinePayload]
    generated: Sequence[PipelinePayload]
    approved: Sequence[PipelinePayload]

    def summary(self) -> str:
        return (
            f"crawled={len(self.crawled)} "
            f"generated={len(self.generated)} "
            f"approved={len(self.approved)}"
        )


async def _run_crawler(targets: Dict[str, Any]) -> List[PipelinePayload]:
    try:
        from src.services import crawler
    except ImportError as exc:  # pragma: no cover - defensive guard
        raise SystemExit("Crawler service module missing. Did you set up src/services/crawler.py?") from exc

    LOGGER.info("Running crawler step...")
    keywords = targets.get("keywords", [])
    hashtags = targets.get("hashtags", [])
    query = {
        "keywords": keywords,
        "hashtags": hashtags,
        "sources": targets.get("sources", []),
        "time_window_days": targets.get("time_window_days", 1),
    }

    if hasattr(crawler, "fetch_fragments"):
        result = await _maybe_await(crawler.fetch_fragments(query))
    elif hasattr(crawler, "run"):
        result = await _maybe_await(crawler.run(query))
    else:
        LOGGER.warning(
            "Crawler service missing expected entrypoints. Falling back to sample data."
        )
        result = _sample_crawl_payload(keywords, hashtags)

    LOGGER.info("Crawler step completed with %d items.", len(result))
    return list(result)


async def _run_generator(posts: Sequence[PipelinePayload]) -> List[PipelinePayload]:
    try:
        from src.services import generator
    except ImportError as exc:  # pragma: no cover - defensive guard
        raise SystemExit("Generator service module missing. Did you set up src/services/generator.py?") from exc

    LOGGER.info("Running generator step...")
    if hasattr(generator, "generate_responses"):
        result = await _maybe_await(generator.generate_responses(posts))
    elif hasattr(generator, "run"):
        result = await _maybe_await(generator.run(posts))
    else:
        LOGGER.warning(
            "Generator service missing expected entrypoints. Using placeholder responses."
        )
        result = _sample_generation_payload(posts)

    LOGGER.info("Generator step produced %d responses.", len(result))
    return list(result)


def _run_safety_filter(
    posts: Sequence[PipelinePayload], blocklist: Sequence[str]
) -> List[PipelinePayload]:
    try:
        from src.services import safety
    except ImportError as exc:  # pragma: no cover - defensive guard
        raise SystemExit("Safety service module missing. Did you set up src/services/safety.py?") from exc

    LOGGER.info("Running safety filter step...")
    if hasattr(safety, "filter_responses"):
        filtered = safety.filter_responses(posts, blocklist=blocklist)
    elif hasattr(safety, "run"):
        filtered = safety.run(posts, blocklist=blocklist)
    else:
        LOGGER.warning(
            "Safety service missing expected entrypoints. Using naive keyword filter."
        )
        filtered = [
            post
            for post in posts
            if not _contains_blocklisted_term(post.get("content", ""), blocklist)
        ]

    LOGGER.info(
        "Safety filter approved %d of %d responses.", len(filtered), len(posts)
    )
    return list(filtered)


async def _run_poster(posts: Sequence[PipelinePayload]) -> None:
    try:
        from src.services import poster
    except ImportError as exc:  # pragma: no cover - defensive guard
        raise SystemExit("Poster service module missing. Did you set up src/services/poster.py?") from exc

    LOGGER.info("Running posting step...")
    if not posts:
        LOGGER.info("No posts approved. Skipping posting step.")
        return

    if hasattr(poster, "publish_batch"):
        await _maybe_await(poster.publish_batch(posts))
    elif hasattr(poster, "run"):
        await _maybe_await(poster.run(posts))
    else:
        LOGGER.warning(
            "Poster service missing expected entrypoints. Outputting payload instead."
        )
        for post in posts:
            LOGGER.info("POST (dry-run): %s", post.get("content", "<no content>"))

    LOGGER.info("Posting step completed.")


async def _maybe_await(value: Any) -> Any:
    if asyncio.iscoroutine(value) or isinstance(value, asyncio.Future):
        return await value
    return value


def _contains_blocklisted_term(content: str, blocklist: Sequence[str]) -> bool:
    lowered = content.lower()
    return any(term.lower() in lowered for term in blocklist)


def _sample_crawl_payload(
    keywords: Sequence[str], hashtags: Sequence[str]
) -> List[PipelinePayload]:
    sample_text = ", ".join(keywords[:2] or ["AI"]) + " insights for devs."
    return [
        {
            "id": "sample-post-1",
            "content": sample_text,
            "metadata": {"hashtags": hashtags[:2], "source": "sample"},
        }
    ]


def _sample_generation_payload(
    posts: Sequence[PipelinePayload],
) -> List[PipelinePayload]:
    generated: List[PipelinePayload] = []
    for idx, post in enumerate(posts, start=1):
        content = post.get("content", "")
        generated.append(
            {
                "source_id": post.get("id", f"unknown-{idx}"),
                "content": f"Appreciate the insights! Have you tried applying this with Python + FastAPI? {content}",
            }
        )
    return generated


async def run_pipeline() -> PipelineResult:
    project_root = Path(__file__).resolve().parents[1]
    env_path = project_root / ".env"
    targets_path = project_root / "config" / "targets.json"
    blocklist_path = project_root / "config" / "blocklist.txt"

    _load_dotenv(env_path)
    targets = _load_targets_config(targets_path)
    blocklist = _load_blocklist(blocklist_path)

    crawled = await _run_crawler(targets)
    generated = await _run_generator(crawled)
    approved = _run_safety_filter(generated, blocklist)
    await _run_poster(approved)

    return PipelineResult(crawled=crawled, generated=generated, approved=approved)


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s - %(message)s",
    )

    result = await run_pipeline()
    LOGGER.info("Pipeline completed: %s", result.summary())


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:  # pragma: no cover - user initiated abort
        raise SystemExit("Pipeline test interrupted by user.")
