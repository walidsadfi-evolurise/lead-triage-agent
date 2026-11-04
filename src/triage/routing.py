"""Rule-based routing: first matching rule wins, in file order.

Rules are declarative on purpose. The LLM reads the lead; it does not decide who
gets it. That keeps routing auditable and lets ops edit it without redeploying.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from triage.models import Extraction, Lead, Route, Score
from triage.scoring import ScoringWeights


class Match(BaseModel):
    intent: list[str] | None = None
    urgency: list[str] | None = None
    tier: list[str] | None = None
    service: list[str] | None = Field(default=None, description="Case-insensitive substrings")
    location: list[str] | None = Field(default=None, description="Case-insensitive substrings")
    language: list[str] | None = None
    channel: list[str] | None = None
    sensitive: bool | None = None
    min_score: int | None = None
    max_score: int | None = None


class Rule(BaseModel):
    name: str
    match: Match = Field(default_factory=Match)
    team: str
    owner: str | None = None
    sla_hours: int = 24
    action: str = Field(default="assign", pattern="^(auto_reply|assign|escalate|discard)$")
    reply_template: str | None = None


class RoutingConfig(BaseModel):
    weights: ScoringWeights = Field(default_factory=ScoringWeights)
    rules: list[Rule]
    default: Rule = Field(
        default_factory=lambda: Rule(name="default", team="sales", sla_hours=48, action="assign")
    )
    needs_human_below_confidence: float = 0.5
    auto_reply_min_tier: str = "B"
    templates: dict[str, str] = Field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> RoutingConfig:
        return cls.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def _in(value: Any, allowed: list[str] | None) -> bool:
    return allowed is None or str(value) in allowed


def _contains(value: str | None, needles: list[str] | None) -> bool:
    if needles is None:
        return True
    if not value:
        return False
    v = value.lower()
    return any(n.lower() in v for n in needles)


def matches(rule: Rule, lead: Lead, ex: Extraction, score: Score) -> bool:
    m = rule.match
    return (
        _in(ex.intent.value, m.intent)
        and _in(ex.urgency.value, m.urgency)
        and _in(score.tier, m.tier)
        and _contains(ex.service, m.service)
        and _contains(ex.location, m.location)
        and _in(ex.language, m.language)
        and _in(lead.channel.value, m.channel)
        and (m.sensitive is None or ex.sensitive == m.sensitive)
        and (m.min_score is None or score.total >= m.min_score)
        and (m.max_score is None or score.total <= m.max_score)
    )


def route(cfg: RoutingConfig, lead: Lead, ex: Extraction, score: Score) -> tuple[Route, Rule]:
    for rule in cfg.rules:
        if matches(rule, lead, ex, score):
            return Route(team=rule.team, owner=rule.owner, sla_hours=rule.sla_hours, rule=rule.name), rule
    d = cfg.default
    return Route(team=d.team, owner=d.owner, sla_hours=d.sla_hours, rule=d.name), d
