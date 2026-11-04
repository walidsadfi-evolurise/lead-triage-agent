"""Structured extraction from free text: LLM with JSON output, rule-based fallback.

The rule-based extractor is not a toy: it is the fallback when the model is
down, returns invalid JSON or is not configured, and it is what the test suite
runs against. Its confidence is capped so downstream code knows to be careful.
"""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod

from pydantic import ValidationError

from triage.llm import LLM
from triage.models import Extraction, Intent, Lead, Urgency

SYSTEM_PROMPT = """You extract structured fields from an inbound business lead.
Return ONLY a JSON object with these keys:
intent: one of quote, appointment, information, support, partnership, job, spam, other
service: short string or null
urgency: one of low, normal, high, emergency
location: city/region string or null
budget_mentioned: boolean
timeline: short string or null
language: fr | en | other
summary: one neutral sentence, max 300 chars, no personal data
sensitive: true if health, legal, financial distress or minors are mentioned
confidence: number 0..1
Never add keys. Never include the person's name, email or phone in summary."""

_KEYWORDS: dict[Intent, tuple[str, ...]] = {
    Intent.appointment: (
        "rendez-vous",
        "rdv",
        "appointment",
        "créneau",
        "disponibilit",
        "consultation",
        "slot",
        "book",
    ),
    Intent.quote: ("devis", "quote", "tarif", "prix", "price", "pricing", "budget", "proposal", "combien"),
    Intent.support: (
        "bug",
        "problème",
        "probleme",
        "ne fonctionne",
        "doesn't work",
        "not working",
        "panne",
        "erreur",
        "error",
        "facture",
        "invoice",
    ),
    Intent.partnership: ("partenariat", "partnership", "revendeur", "reseller", "collaboration", "affiliat"),
    Intent.job: ("candidature", "cv ", "stage", "alternance", "job", "poste", "recrut", "hiring", "resume"),
    Intent.spam: (
        "seo services",
        "backlinks",
        "crypto",
        "casino",
        "guaranteed ranking",
        "buy followers",
        "viagra",
    ),
    Intent.information: (
        "question",
        "renseignement",
        "information",
        "savoir si",
        "is it possible",
        "est-ce que",
        "comment",
    ),
}
_EMERGENCY = (
    "urgence",
    "urgent",
    "emergency",
    "asap",
    "immédiat",
    "immediat",
    "tout de suite",
    "aujourd'hui",
    "today",
    "right now",
)
_HIGH = ("rapidement", "quickly", "cette semaine", "this week", "dès que possible", "soon", "deadline")
_LOW = ("pas pressé", "no rush", "éventuellement", "un jour", "someday", "curiosit")
_SENSITIVE = (
    "douleur",
    "pain",
    "symptôme",
    "symptom",
    "médic",
    "medical",
    "ordonnance",
    "prescription",
    "avocat",
    "lawyer",
    "procès",
    "lawsuit",
    "dette",
    "debt",
    "huissier",
    "enfant",
    "child",
    "mineur",
    "minor",
    "hospital",
    "hôpital",
    "saign",
    "bleed",
)
_EN_MARKERS = (" the ", " is ", " i ", " we ", " you ", " please", " would", " need", " want")
_FR_MARKERS = (
    " le ",
    " la ",
    " les ",
    " je ",
    " nous ",
    " vous ",
    " bonjour",
    " merci",
    " est ",
    " une ",
    " des ",
)
_LOCATION = re.compile(
    r"\b(?:à|a|in|sur|near|près de|pres de|from|de)\s+([A-ZÀ-Ý][\w'\-]+(?:\s[A-ZÀ-Ý][\w'\-]+)?)"
)
_MONTHS_FR = "janvier|février|mars|avril|mai|juin|juillet|août|septembre|octobre|novembre|décembre"
_MONTHS_EN = "january|february|march|april|may|june|july|august|september|october|november|december"
_RELATIVE = (
    "cette semaine|this week|ce mois|this month|la semaine prochaine|next week|demain|tomorrow|asap|q[1-4]"
)
_TIMELINE = re.compile(
    rf"\b({_RELATIVE}|{_MONTHS_FR}|{_MONTHS_EN}|\d{{1,2}}/\d{{1,2}}(?:/\d{{2,4}})?)\b", re.I
)


class Extractor(ABC):
    name: str = "base"

    @abstractmethod
    def extract(self, lead: Lead) -> Extraction: ...


class RuleBasedExtractor(Extractor):
    name = "rules"

    def extract(self, lead: Lead) -> Extraction:
        text = f" {lead.message.lower()} "
        scores = {intent: sum(text.count(k) for k in kws) for intent, kws in _KEYWORDS.items()}
        best = max(scores, key=lambda i: scores[i])
        intent = best if scores[best] > 0 else Intent.other
        if (
            scores[Intent.spam] > 0
            and not lead.phone
            and (
                lead.email is None
                or lead.email.split("@")[1] in {"mail.ru", "qq.com"}
                or scores[Intent.spam] >= 2
            )
        ):
            intent = Intent.spam

        if any(k in text for k in _EMERGENCY):
            urgency = (
                Urgency.emergency
                if any(
                    k in text for k in ("urgence", "emergency", "saign", "bleed", "douleur intense", "severe")
                )
                else Urgency.high
            )
        elif any(k in text for k in _HIGH):
            urgency = Urgency.high
        elif any(k in text for k in _LOW):
            urgency = Urgency.low
        else:
            urgency = Urgency.normal

        en = sum(text.count(m) for m in _EN_MARKERS)
        fr = sum(text.count(m) for m in _FR_MARKERS)
        language: str = "fr" if fr >= en and fr > 0 else "en" if en > 0 else "other"

        loc = _LOCATION.search(lead.message)
        tl = _TIMELINE.search(lead.message)
        sensitive = any(k in text for k in _SENSITIVE)
        matched = scores[best] if intent is not Intent.other else 0
        competing = sum(1 for i, n in scores.items() if n > 0 and i is not intent)
        confidence = (
            0.4
            + 0.15 * min(matched, 2)
            + (0.1 if matched and not competing else 0.0)
            + (0.05 if loc else 0.0)
        )
        confidence = min(0.8, confidence)
        words = lead.message.split()
        summary = (
            f"{intent.value} request"
            + (f" about {lead.extra['service']}" if "service" in lead.extra else "")
            + f" ({len(words)} words)"
        )
        return Extraction(
            intent=intent,
            service=lead.extra.get("service"),
            urgency=urgency,
            location=loc.group(1) if loc else None,
            budget_mentioned=bool(re.search(r"\d+\s?(€|eur|k€|\$|usd)|budget", text)),
            timeline=tl.group(1) if tl else None,
            language=language,  # type: ignore[arg-type]
            summary=summary[:300],
            sensitive=sensitive,
            confidence=confidence,
        )


class LLMExtractor(Extractor):
    """Asks the model for JSON, validates it, falls back to rules on any failure."""

    name = "llm"

    def __init__(self, llm: LLM, fallback: Extractor | None = None) -> None:
        self.llm = llm
        self.fallback = fallback or RuleBasedExtractor()
        self.last_error: str | None = None

    def extract(self, lead: Lead) -> Extraction:
        self.last_error = None
        fields = json.dumps(lead.extra, ensure_ascii=False)
        header = f"Channel: {lead.channel}\nSource: {lead.source or '-'}\nFields: {fields}"
        user = f"{header}\n\nMessage:\n{lead.message}"
        try:
            raw = self.llm.complete(SYSTEM_PROMPT, user, max_tokens=400)
            m = re.search(r"\{.*\}", raw, re.S)
            if not m:
                raise ValueError("no JSON object in model output")
            data = json.loads(m.group(0))
            return Extraction.model_validate(data)
        except (ValueError, ValidationError, json.JSONDecodeError) as e:  # noqa: PERF203 — one call, not a loop
            self.last_error = f"{type(e).__name__}: {e}"
        except Exception as e:  # network / provider errors
            self.last_error = f"{type(e).__name__}: {e}"
        fb = self.fallback.extract(lead)
        return fb.model_copy(update={"confidence": min(fb.confidence, 0.5)})
