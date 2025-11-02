"""Safety filtering for generated replies."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional, Sequence

from src.services.generator import GeneratedReply
from src.utils.config import get_settings, load_blocklist
from src.utils.logger import get_logger, set_correlation_id

LOGGER = get_logger("services.safety")


@dataclass(frozen=True)
class SafetyDecision:
    id: str
    approved: bool
    content: str
    reason: Optional[str]
    reviewed_at: datetime
    confidence: float


class SafetyFilter:
    """Applies length and keyword checks to generated replies."""

    def __init__(self) -> None:
        self._settings = get_settings()
        self._blocklist = load_blocklist()

    def evaluate(self, replies: Sequence[GeneratedReply]) -> List[SafetyDecision]:
        decisions: List[SafetyDecision] = []
        for reply in replies:
            correlation_id = f"safety-{reply.id}"
            set_correlation_id(correlation_id)
            decision = self._evaluate_single(reply)
            decisions.append(decision)
        return decisions

    def _evaluate_single(self, reply: GeneratedReply) -> SafetyDecision:
        reason = self._find_failure_reason(reply)
        approved = reason is None
        if approved and self._requires_manual_review(reply):
            reason = "manual_review"
            approved = False
        if approved:
            LOGGER.info("Reply approved", extra={"tweet_id": reply.id})
        else:
            LOGGER.warning("Reply flagged", extra={"tweet_id": reply.id, "reason": reason})

        return SafetyDecision(
            id=reply.id,
            approved=approved,
            content=reply.content,
            reason=reason,
            reviewed_at=datetime.now(timezone.utc),
            confidence=reply.confidence,
        )

    def _find_failure_reason(self, reply: GeneratedReply) -> Optional[str]:
        content = reply.content.strip()
        safety_cfg = self._settings.safety

        if reply.error:
            return f"generation_error:{reply.error}"
        if not content:
            return "empty_reply"
        if len(content) < safety_cfg.content_min_length:
            return "too_short"
        if len(content) > safety_cfg.content_max_length:
            return "too_long"

        lower_content = content.lower()
        for term in self._blocklist:
            if term and term in lower_content:
                return f"blocked_term:{term}"

        return None

    def _requires_manual_review(self, reply: GeneratedReply) -> bool:
        safety_cfg = self._settings.safety
        if not safety_cfg.enable_manual_review:
            return False
        return reply.confidence < safety_cfg.manual_review_threshold


_FILTER: Optional[SafetyFilter] = None


def get_filter() -> SafetyFilter:
    global _FILTER
    if _FILTER is None:
        _FILTER = SafetyFilter()
    return _FILTER


def evaluate_replies(replies: Sequence[GeneratedReply]) -> List[SafetyDecision]:
    safety_filter = get_filter()
    return safety_filter.evaluate(replies)


__all__ = ["SafetyDecision", "SafetyFilter", "evaluate_replies", "get_filter"]
