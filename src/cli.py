"""Command-line utilities for running the automation pipeline."""

from __future__ import annotations

import argparse
import asyncio
from typing import Sequence

from src.services.crawler import CrawlResult, fetch_fragments
from src.services.generator import GenerationRequest, ReplyGenerator, generate_responses
from src.services.safety import SafetyDecision, evaluate_replies
from src.utils.logger import get_logger, set_correlation_id

LOGGER = get_logger("cli")


async def _run_pipeline(limit: int) -> tuple[Sequence[CrawlResult], Sequence[SafetyDecision]]:
    set_correlation_id("cli-crawl")
    crawl_results = await fetch_fragments()
    if limit > 0:
        crawl_results = crawl_results[:limit]

    if not crawl_results:
        LOGGER.info("No crawl results returned")
        return [], []

    generator = ReplyGenerator()
    try:
        requests = [GenerationRequest(target=result, media=getattr(result, "media", [])) for result in crawl_results]
        replies = await generator.generate(requests)
    finally:
        await generator.aclose()

    decisions = evaluate_replies(replies)
    return crawl_results, decisions


def run(limit: int = 5) -> None:
    results, decisions = asyncio.run(_run_pipeline(limit))
    if not results:
        print("No tweets discovered.")
        return

    print(f"Processed {len(results)} tweets. Safety outcomes:")
    for decision in decisions:
        status = "APPROVED" if decision.approved else f"FLAGGED ({decision.reason})"
        print(f"- {decision.id}: {status}")
        if decision.approved:
            print(f"  Reply: {decision.content}")


def main() -> None:
    parser = argparse.ArgumentParser(description="X automation pipeline CLI")
    subparsers = parser.add_subparsers(dest="command")

    run_parser = subparsers.add_parser("run", help="Run crawl → generate → safety pipeline")
    run_parser.add_argument("--limit", type=int, default=5, help="Max tweets to process (0 = unlimited)")

    args = parser.parse_args()
    if args.command == "run":
        run(limit=args.limit)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
