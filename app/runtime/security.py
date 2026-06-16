from __future__ import annotations

from dataclasses import dataclass, field

from app.domain.models import AgentIntentType, DisclosureMode, PlayerAction


@dataclass(frozen=True)
class PromptInjectionReview:
    risk_level: str
    matched_patterns: list[str] = field(default_factory=list)
    recommended_response_mode: str | None = None

    @property
    def security_flags(self) -> list[str]:
        if not self.matched_patterns:
            return []
        return [
            f"prompt_injection.{self.risk_level}",
            *[f"prompt_injection.pattern.{pattern}" for pattern in self.matched_patterns],
        ]

    @property
    def requires_hard_restriction(self) -> bool:
        return self.risk_level == "high"

    @property
    def allowed_intents(self) -> list[AgentIntentType] | None:
        if not self.requires_hard_restriction:
            return None
        return [AgentIntentType.REFUSE, AgentIntentType.CONCEAL]

    @property
    def max_disclosure_mode(self) -> DisclosureMode | None:
        if not self.requires_hard_restriction:
            return None
        return DisclosureMode.DEFLECT


class PromptInjectionGuard:
    _PATTERNS = {
        "ignore_rules": (
            "ignore system",
            "ignore previous",
            "ignore all previous",
            "forget your instructions",
            "bypass",
        ),
        "prompt_exfiltration": (
            "system prompt",
            "developer message",
            "hidden prompt",
            "show your instructions",
        ),
        "private_exfiltration": (
            "hidden truth",
            "private data",
            "secret rules",
            "reveal the killer",
            "solution claims",
        ),
        "schema_override": (
            "do not return json",
            "ignore the schema",
            "extra field",
            "change the json",
        ),
        "role_override": (
            "you are the director",
            "i am the developer",
            "i am admin",
            "out of character",
        ),
    }

    def review(self, action: PlayerAction) -> PromptInjectionReview:
        text = (action.text or "").lower()
        matched = [
            pattern_id
            for pattern_id, needles in self._PATTERNS.items()
            if any(needle in text for needle in needles)
        ]
        if not matched:
            return PromptInjectionReview(risk_level="none")
        risk_level = "high" if len(matched) >= 2 else "low"
        return PromptInjectionReview(
            risk_level=risk_level,
            matched_patterns=matched,
            recommended_response_mode="refuse" if risk_level == "high" else "deflect",
        )
