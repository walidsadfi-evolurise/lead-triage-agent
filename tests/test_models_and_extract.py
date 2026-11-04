from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from triage.extract import SYSTEM_PROMPT, LLMExtractor, RuleBasedExtractor
from triage.llm import FakeLLM
from triage.models import Intent, Lead, Urgency


def test_lead_normalises_phone_and_rejects_short_numbers() -> None:
    assert Lead(message="x", phone="+33 6 12 34 56 78").phone == "+33612345678"
    assert Lead(message="x", phone="12 34").phone is None
    with pytest.raises(ValidationError):
        Lead(message="")
    with pytest.raises(ValidationError):
        Lead(message="x", email="not-an-email")


def test_fingerprint_is_stable_and_contact_sensitive() -> None:
    a = Lead(message="Bonjour, un devis svp", email="A@x.com")
    b = Lead(message="bonjour, un devis svp ", email="a@x.com")
    c = Lead(message="Bonjour, un devis svp", email="b@x.com")
    assert a.fingerprint() == b.fingerprint() != c.fingerprint()


@pytest.mark.parametrize(
    ("message", "intent", "urgency"),
    [
        ("Je voudrais prendre rendez-vous à Lyon", Intent.appointment, Urgency.normal),
        ("Pouvez-vous m'envoyer un devis rapidement ?", Intent.quote, Urgency.high),
        ("Urgence : ma dent saigne depuis ce matin", Intent.other, Urgency.emergency),
        ("Le site ne fonctionne plus depuis la mise à jour", Intent.support, Urgency.normal),
        ("We offer SEO services and backlinks, guaranteed ranking", Intent.spam, Urgency.normal),
        ("Candidature pour le poste d'assistante", Intent.job, Urgency.normal),
        (
            "Pas pressé, juste par curiosité : est-ce que vous faites du blanchiment ?",
            Intent.information,
            Urgency.low,
        ),
    ],
)
def test_rule_based_intent_and_urgency(message: str, intent: Intent, urgency: Urgency) -> None:
    ex = RuleBasedExtractor().extract(Lead(message=message))
    assert ex.intent is intent
    assert ex.urgency is urgency


def test_rule_based_fields() -> None:
    ex = RuleBasedExtractor().extract(
        Lead(
            message="Hi, I would like to book an appointment in Paris next week, budget 300 €.",
            extra={"service": "implant"},
        )
    )
    assert ex.language == "en"
    assert ex.location == "Paris"
    assert ex.timeline == "next week"
    assert ex.budget_mentioned
    assert ex.service == "implant"
    assert ex.confidence >= 0.6
    assert "implant" in ex.summary
    assert not ex.sensitive
    assert RuleBasedExtractor().extract(Lead(message="J'ai une douleur depuis trois jours")).sensitive


def test_llm_extractor_uses_model_json_when_valid() -> None:
    reply = json.dumps(
        {
            "intent": "appointment",
            "service": "orthodontie",
            "urgency": "high",
            "location": "Lyon",
            "budget_mentioned": False,
            "timeline": "cette semaine",
            "language": "fr",
            "summary": "Demande de rendez-vous en orthodontie.",
            "sensitive": False,
            "confidence": 0.92,
        }
    )
    llm = FakeLLM(["Here you go:\n" + reply])
    ex = LLMExtractor(llm).extract(Lead(message="RDV ortho svp", name="Zoé"))
    assert ex.service == "orthodontie" and ex.confidence == 0.92
    assert "RDV ortho svp" in llm.calls[0]
    assert "Never include the person's name" in SYSTEM_PROMPT


def test_llm_extractor_falls_back_on_bad_json_and_caps_confidence() -> None:
    for bad in [
        "not json at all",
        '{"intent": "nonsense"}',
        json.dumps({"intent": "quote", "summary": "x" * 400, "confidence": 0.9}),
    ]:
        extractor = LLMExtractor(FakeLLM([bad]))
        ex = extractor.extract(Lead(message="Je voudrais un devis pour 3 cabinets"))
        assert ex.intent is Intent.quote, bad
        assert ex.confidence <= 0.5
        assert extractor.last_error


def test_llm_extractor_survives_provider_errors() -> None:
    class Boom(FakeLLM):
        def complete(self, system: str, user: str, max_tokens: int = 400, temperature: float = 0.0) -> str:
            raise ConnectionError("provider down")

    extractor = LLMExtractor(Boom())
    ex = extractor.extract(Lead(message="rendez-vous svp"))
    assert ex.intent is Intent.appointment
    assert "ConnectionError" in (extractor.last_error or "")
