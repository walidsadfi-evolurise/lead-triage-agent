"""Evaluate routing decisions against labelled leads.

A case is a lead plus the expected team, action, tier and/or needs_human. The
report tells you which rules misfire — the number to watch when you edit
routing.yaml or swap the model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from triage.agent import TriageAgent
from triage.models import Decision, Lead


@dataclass
class Case:
    lead: Lead
    expect_team: str | None = None
    expect_action: str | None = None
    expect_tier: str | None = None
    expect_needs_human: bool | None = None
    expect_intent: str | None = None
    note: str = ""


@dataclass
class CaseResult:
    case: Case
    decision: Decision
    failures: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failures


@dataclass
class Report:
    results: list[CaseResult]

    def summary(self) -> dict[str, float]:
        n = len(self.results) or 1

        def acc(attr: str, get: Any) -> float:
            rel = [r for r in self.results if getattr(r.case, attr) is not None]
            return sum(1 for r in rel if get(r) == getattr(r.case, attr)) / len(rel) if rel else 1.0

        esc = [r for r in self.results if r.case.expect_needs_human is True]
        return {
            "cases": float(len(self.results)),
            "pass_rate": sum(1 for r in self.results if r.ok) / n,
            "team_accuracy": acc("expect_team", lambda r: r.decision.route.team),
            "action_accuracy": acc("expect_action", lambda r: r.decision.action),
            "tier_accuracy": acc("expect_tier", lambda r: r.decision.score.tier),
            "intent_accuracy": acc("expect_intent", lambda r: r.decision.extraction.intent.value),
            "escalation_recall": (sum(1 for r in esc if r.decision.needs_human) / len(esc)) if esc else 1.0,
        }


def load_cases(path: Path) -> list[Case]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    cases = []
    for item in raw:
        lead = Lead.model_validate(item["lead"])
        cases.append(Case(lead=lead, **{k: v for k, v in item.items() if k != "lead"}))
    return cases


def evaluate(agent: TriageAgent, cases: list[Case]) -> Report:
    results = []
    for c in cases:
        d = agent.decide(c.lead)
        fails = []
        if c.expect_team is not None and d.route.team != c.expect_team:
            fails.append(f"team {d.route.team} != {c.expect_team}")
        if c.expect_action is not None and d.action != c.expect_action:
            fails.append(f"action {d.action} != {c.expect_action}")
        if c.expect_tier is not None and d.score.tier != c.expect_tier:
            fails.append(f"tier {d.score.tier} != {c.expect_tier}")
        if c.expect_needs_human is not None and d.needs_human != c.expect_needs_human:
            fails.append(f"needs_human {d.needs_human} != {c.expect_needs_human}")
        if c.expect_intent is not None and d.extraction.intent.value != c.expect_intent:
            fails.append(f"intent {d.extraction.intent.value} != {c.expect_intent}")
        results.append(CaseResult(c, d, fails))
    return Report(results)
