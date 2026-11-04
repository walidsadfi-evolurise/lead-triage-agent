"""Data contracts. Everything the agent produces is typed and serialisable."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator


class Channel(StrEnum):
    form = "form"
    email = "email"
    chat = "chat"
    phone = "phone"
    api = "api"


class Lead(BaseModel):
    """Raw inbound lead, as the website form / mailbox / CRM webhook delivers it."""

    lead_id: str | None = None
    channel: Channel = Channel.form
    received_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    name: str | None = None
    email: EmailStr | None = None
    phone: str | None = None
    company: str | None = None
    message: str = Field(min_length=1, max_length=20_000)
    source: str | None = Field(default=None, description="Landing page, campaign, referrer…")
    extra: dict[str, str] = Field(default_factory=dict)

    @field_validator("phone")
    @classmethod
    def _phone(cls, v: str | None) -> str | None:
        if v is None:
            return None
        digits = "".join(ch for ch in v if ch.isdigit() or ch == "+")
        return digits if len(digits.lstrip("+")) >= 8 else None

    def fingerprint(self) -> str:
        """Stable id for dedupe: same contact + same message within a window."""
        key = f"{(self.email or '').lower()}|{self.phone or ''}|{self.message.strip().lower()[:200]}"
        return hashlib.sha256(key.encode()).hexdigest()[:16]


class Urgency(StrEnum):
    low = "low"
    normal = "normal"
    high = "high"
    emergency = "emergency"


class Intent(StrEnum):
    quote = "quote"  # wants a price / proposal
    appointment = "appointment"  # wants a slot
    information = "information"  # question before buying
    support = "support"  # existing customer issue
    partnership = "partnership"
    job = "job"
    spam = "spam"
    other = "other"


class Extraction(BaseModel):
    """What the LLM (or the rule-based fallback) reads out of the free text."""

    intent: Intent
    service: str | None = Field(default=None, description="Service / product line the lead asks about")
    urgency: Urgency = Urgency.normal
    location: str | None = None
    budget_mentioned: bool = False
    timeline: str | None = Field(default=None, description="e.g. 'this week', 'Q1', 'asap'")
    language: Literal["fr", "en", "other"] = "fr"
    summary: str = Field(max_length=300)
    sensitive: bool = Field(
        default=False, description="Health, legal, financial distress or minors mentioned"
    )
    confidence: float = Field(ge=0, le=1)


class Factor(BaseModel):
    name: str
    points: int
    why: str


class Score(BaseModel):
    total: int = Field(ge=0, le=100)
    tier: Literal["A", "B", "C", "D"]
    factors: list[Factor]


class Route(BaseModel):
    team: str
    owner: str | None = None
    sla_hours: int
    rule: str = Field(description="Name of the routing rule that matched")


class Decision(BaseModel):
    lead_id: str
    fingerprint: str
    extraction: Extraction
    score: Score
    route: Route
    action: Literal["auto_reply", "assign", "escalate", "discard"]
    needs_human: bool
    reasons: list[str]
    reply_draft: str | None = None
    decided_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    model: str
