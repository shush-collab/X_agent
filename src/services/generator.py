"""Reply generation service using Perplexity API."""

from __future__ import annotations

import asyncio
import json
import os
import random
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional, Protocol, Sequence

import httpx

from src.services.crawler import CrawlResult  # for type reuse
from src.utils.config import get_settings
from src.utils.logger import get_logger, set_correlation_id
from src.utils.html_parser import ParsedMedia

LOGGER = get_logger("services.generator")

PROMPT_TEMPLATE = """
You are a technical expert commenting on X. Reply to this tweet:

Tweet: {tweet_text}
Author: {author_handle}

Guidelines:
- Be insightful, not promotional
- Max 280 characters
- Casual but professional tone
- Add value to the conversation
- No emoji overload (1-2 max)
""".strip()

PERPLEXITY_ENDPOINT = "https://api.perplexity.ai/chat/completions"


class ReplyTarget(Protocol):
    id: str
    content: str
    author_handle: str


@dataclass
class GeneratedReply:
    id: str
    content: str
    confidence: float
    model_used: str
    generated_at: datetime
    error: Optional[str] = None


@dataclass
class GenerationRequest:
    target: ReplyTarget
    media: List[ParsedMedia]


class ReplyGenerator:
    """Handles prompt creation and calls to the Perplexity API."""

    def __init__(self) -> None:
        self._settings = get_settings()
        self._headers = {
            "Authorization": f"Bearer {self._settings.perplexity_api_key}",
            "Content-Type": "application/json",
        }
        timeout = httpx.Timeout(30.0, connect=10.0)
        self._client = httpx.AsyncClient(timeout=timeout)
        self._rate_window: deque[datetime] = deque()
        self._max_rpm = int(os.getenv("PERPLEXITY_MAX_RPM", "60"))
        self._max_attempts = 4
        self._cache_enabled = self._settings.app_env == "development"
        self._cache: Dict[str, GeneratedReply] = {}

    async def generate(self, requests: Sequence[GenerationRequest]) -> List[GeneratedReply]:
        replies: List[GeneratedReply] = []
        for request in requests:
            correlation_id = f"gen-{request.target.id}"
            set_correlation_id(correlation_id)

            if self._cache_enabled and request.target.id in self._cache:
                LOGGER.debug("Returning cached reply", extra={"tweet_id": request.target.id})
                replies.append(self._cache[request.target.id])
                continue

            try:
                reply = await self._generate_single(request)
            except Exception as exc:  # pragma: no cover - defensive fallback
                LOGGER.error("Generation failed", extra={"tweet_id": request.target.id, "error": str(exc)})
                reply = GeneratedReply(
                    id=request.target.id,
                    content="",
                    confidence=0.0,
                    model_used=self._settings.perplexity_model,
                    generated_at=datetime.now(timezone.utc),
                    error=str(exc),
                )

            if self._cache_enabled and reply.error is None:
                self._cache[request.target.id] = reply

            replies.append(reply)
        return replies

    async def _generate_single(self, request: GenerationRequest) -> GeneratedReply:
        prompt = self._build_prompt(request)
        await self._respect_rate_limit()
        payload = self._build_payload(prompt)
        LOGGER.debug(
            "Submitting Perplexity request",
            extra={
                "tweet_id": request.target.id,
                "model": payload.get("model"),
                "prompt_chars": len(prompt),
                "prompt_preview": prompt[:120],
                "media_count": len(request.media),
            },
        )

        response_data, error = await self._call_perplexity(payload)
        generated_at = datetime.now(timezone.utc)

        if error:
            return GeneratedReply(
                id=request.target.id,
                content="",
                confidence=0.0,
                model_used=self._settings.perplexity_model,
                generated_at=generated_at,
                error=error,
            )

        content = response_data.get("content", "")
        confidence = response_data.get("confidence", 0.0)
        model_used = response_data.get("model", self._settings.perplexity_model)

        return GeneratedReply(
            id=request.target.id,
            content=content[:280].strip(),
            confidence=float(confidence or 0.0),
            model_used=model_used,
            generated_at=generated_at,
        )

    def _build_prompt(self, request: GenerationRequest) -> str:
        attachments = ""
        if request.media:
            summary_lines = [f"- {media.alt_text or 'media file'}" for media in request.media]
            attachments = "\nMedia context:\n" + "\n".join(summary_lines)
        return PROMPT_TEMPLATE.format(
            tweet_text=request.target.content.strip(),
            author_handle=f"@{request.target.author_handle}",
        ) + attachments

    def _build_payload(self, prompt: str) -> Dict[str, object]:
        return {
            "model": self._settings.perplexity_model,
            "messages": [
                {"role": "system", "content": "You are a helpful technical expert."},
                {"role": "user", "content": prompt},
            ],
            "max_tokens": 200,
            "temperature": 0.6,
        }

    async def _call_perplexity(self, payload: Dict[str, object]) -> (Dict[str, object], Optional[str]):
        backoff = 1.0
        for attempt in range(1, self._max_attempts + 1):
            try:
                LOGGER.debug(
                    "Perplexity POST attempt",
                    extra={"attempt": attempt, "model": payload.get("model")},
                )
                response = await self._client.post(PERPLEXITY_ENDPOINT, headers=self._headers, json=payload)
            except httpx.TimeoutException:
                LOGGER.warning("Perplexity timeout", extra={"attempt": attempt})
                error = "timeout"
            except httpx.HTTPError as exc:
                LOGGER.warning("Perplexity HTTP error", extra={"attempt": attempt, "error": str(exc)})
                error = str(exc)
            else:
                if response.status_code == 429:
                    LOGGER.warning("Perplexity rate limited", extra={"attempt": attempt})
                    error = "rate_limited"
                elif response.status_code >= 500:
                    LOGGER.warning("Perplexity server error", extra={"status": response.status_code})
                    error = f"server_{response.status_code}"
                elif not response.is_success:
                    error_details = self._extract_error_payload(response)
                    LOGGER.error(
                        "Perplexity request failed",
                        extra={
                            "status": response.status_code,
                            "body": response.text[:200],
                            "error_details": error_details,
                        },
                    )
                    return {}, f"http_{response.status_code}"
                else:
                    try:
                        data = response.json()
                    except json.JSONDecodeError:
                        LOGGER.error("Perplexity returned invalid JSON")
                        return {}, "invalid_json"
                    content, error = self._extract_content(data)
                    if error:
                        return {}, error
                    return content, None

            if attempt == self._max_attempts:
                return {}, error
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30) + random.uniform(0, 1)

        return {}, "unknown_error"

    def _extract_content(self, data: Dict[str, object]) -> (Dict[str, object], Optional[str]):
        choices = data.get("choices")
        if not choices:
            return {}, "no_choices"
        choice = choices[0]
        message = choice.get("message") if isinstance(choice, dict) else None
        if not message:
            return {}, "missing_message"
        if message.get("refusal"):
            return {}, "refused"
        content = message.get("content", "").strip()
        if not content:
            return {}, "empty_content"
        return {
            "content": content,
            "confidence": choice.get("confidence", 0.0),
            "model": data.get("model", self._settings.perplexity_model),
        }, None

    @staticmethod
    def _extract_error_payload(response: httpx.Response) -> Dict[str, object]:
        try:
            payload = response.json()
        except json.JSONDecodeError:
            return {}
        if isinstance(payload, dict):
            truncated = {}
            for key, value in payload.items():
                if isinstance(value, str):
                    truncated[key] = value[:200]
                elif isinstance(value, dict):
                    truncated[key] = {k: (v[:200] if isinstance(v, str) else v) for k, v in value.items()}
                else:
                    truncated[key] = value
            return truncated
        return {"raw": payload}

    async def _respect_rate_limit(self) -> None:
        if self._max_rpm <= 0:
            return
        now = datetime.now(timezone.utc)
        while self._rate_window and (now - self._rate_window[0]).total_seconds() >= 60:
            self._rate_window.popleft()
        if len(self._rate_window) >= self._max_rpm:
            earliest = self._rate_window[0]
            wait_seconds = 60 - (now - earliest).total_seconds()
            if wait_seconds > 0:
                LOGGER.debug("Rate limit sleep", extra={"seconds": wait_seconds})
                await asyncio.sleep(wait_seconds)
        self._rate_window.append(datetime.now(timezone.utc))

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "ReplyGenerator":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.aclose()


_GENERATOR: Optional[ReplyGenerator] = None


def get_generator() -> ReplyGenerator:
    global _GENERATOR
    if _GENERATOR is None:
        _GENERATOR = ReplyGenerator()
    return _GENERATOR


async def generate_responses(targets: Sequence[CrawlResult]) -> List[GeneratedReply]:
    generator = get_generator()
    requests = [GenerationRequest(target=target, media=target.media if hasattr(target, "media") else []) for target in targets]
    return await generator.generate(requests)


def run_generation(targets: Sequence[CrawlResult]) -> List[GeneratedReply]:
    return asyncio.run(generate_responses(targets))


__all__ = [
    "GeneratedReply",
    "ReplyGenerator",
    "generate_responses",
    "run_generation",
]
