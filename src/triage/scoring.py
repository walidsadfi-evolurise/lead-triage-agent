"""Explainable lead scoring.

Weights live in the routing config (YAML) so sales ops can change them without
a deploy. Every point is attached to a named factor with a one-line reason, so
"why is this lead a B?" has an answer that a human can read and argue with.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from triage.models import Extraction, Factor, Intent, Lead, Score


class ScoringWeights(BaseModel):
    intent: dict[str, int] = Field(
        default_factory=lambda: {
            "appointment": 35,
            "quote": 30,
            "information": 15,
            "partnership": 10,
            "support": 5,
            "other": 5,
            "job": 0,
            "spam": 0,
        }
    )
    urgency: dict[str, int] = Field(
        default_factory=lambda: {"emergency": 20, "high": 15, "normal": 8, "low": 2}
    )
    has_phone: int = 10
    has_company: int = 8
    budget_mentioned: int = 10
    timeline_mentioned: int = 7
    detailed_message: int = 6  # > 40 words
    service_identified: int = 4
    low_confidence_penalty: int = -8  # extraction confidence < 0.5
    free_mail_penalty: int = -4  # gmail/hotmail… when a company is expected
    tiers: dict[str, int] = Field(
        default_factory=lambda: {"A": 70, "B": 50, "C": 30}
    )  # lower bounds; below C → D


FREE_MAIL = {
    "gmail.com",
    "hotmail.com",
    "hotmail.fr",
    "outlook.com",
    "outlook.fr",
    "yahoo.com",
    "yahoo.fr",
    "live.fr",
    "icloud.com",
    "free.fr",
    "orange.fr",
    "laposte.net",
    "wanadoo.fr",
    "sfr.fr",
}


def score_lead(lead: Lead, ex: Extraction, w: ScoringWeights) -> Score:
    factors: list[Factor] = []

    def add(name: str, points: int, why: str) -> None:
        if points:
            factors.append(Factor(name=name, points=points, why=why))

    if ex.intent in (Intent.spam, Intent.job):
        add("intent", 0, f"{ex.intent.value}: not a sales lead")
        return Score(total=0, tier="D", factors=factors)

    add("intent", w.intent.get(ex.intent.value, 0), f"intent = {ex.intent.value}")
    add("urgency", w.urgency.get(ex.urgency.value, 0), f"urgency = {ex.urgency.value}")
    if lead.phone:
        add("contact", w.has_phone, "phone number provided")
    if lead.company:
        add("company", w.has_company, f"company given ({lead.company})")
    if ex.budget_mentioned:
        add("budget", w.budget_mentioned, "budget or amount mentioned")
    if ex.timeline:
        add("timeline", w.timeline_mentioned, f"timeline mentioned ({ex.timeline})")
    if len(lead.message.split()) > 40:
        add("detail", w.detailed_message, "detailed message (> 40 words)")
    if ex.service:
        add("service", w.service_identified, f"service identified ({ex.service})")
    if ex.confidence < 0.5:
        add("confidence", w.low_confidence_penalty, f"extraction confidence {ex.confidence:.2f}")
    if lead.email and lead.company and lead.email.split("@")[1].lower() in FREE_MAIL:
        add("email", w.free_mail_penalty, "company given but free-mail address")

    total = max(0, min(100, sum(f.points for f in factors)))
    tier = next((t for t, floor in sorted(w.tiers.items(), key=lambda kv: -kv[1]) if total >= floor), "D")
    return Score(total=total, tier=tier, factors=factors)  # type: ignore[arg-type]
