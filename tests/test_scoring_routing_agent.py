from __future__ import annotations

from pathlib import Path

from triage.agent import TriageAgent, render_template
from triage.audit import AuditLog
from triage.extract import RuleBasedExtractor
from triage.models import Extraction, Intent, Lead, Urgency
from triage.routing import RoutingConfig, Rule, matches, route
from triage.scoring import ScoringWeights, score_lead


def _ex(**over: object) -> Extraction:
    base = {"intent": Intent.quote, "summary": "s", "confidence": 0.8}
    return Extraction(**{**base, **over})  # type: ignore[arg-type]


def test_score_is_sum_of_named_factors_and_capped() -> None:
    lead = Lead(message="word " * 50, phone="+33600000000", company="ACME", email="x@acme.fr")
    s = score_lead(
        lead,
        _ex(urgency=Urgency.emergency, budget_mentioned=True, timeline="Q1", service="x"),
        ScoringWeights(),
    )
    assert s.total == sum(f.points for f in s.factors) == 30 + 20 + 10 + 8 + 10 + 7 + 6 + 4
    assert s.tier == "A"
    assert {f.name for f in s.factors} >= {
        "intent",
        "urgency",
        "contact",
        "company",
        "budget",
        "timeline",
        "detail",
        "service",
    }


def test_penalties_and_tiers() -> None:
    lead = Lead(message="devis", company="ACME", email="x@gmail.com")
    s = score_lead(lead, _ex(confidence=0.3), ScoringWeights())
    names = {f.name: f.points for f in s.factors}
    assert names["confidence"] == -8 and names["email"] == -4
    assert s.total == 30 + 8 + 8 - 8 - 4 and s.tier == "C"
    assert score_lead(Lead(message="x"), _ex(intent=Intent.spam), ScoringWeights()).total == 0
    assert score_lead(Lead(message="x"), _ex(intent=Intent.job), ScoringWeights()).tier == "D"


def test_rule_matching_semantics(config: RoutingConfig) -> None:
    lead = Lead(message="x", channel="email")
    ex = _ex(intent=Intent.appointment, location="Villeurbanne Centre", language="fr")
    s = score_lead(lead, ex, config.weights)
    rt, rule = route(config, lead, ex, s)
    assert rule.name == "appointment-lyon" and rt.team == "lyon-front-desk" and rt.sla_hours == 4
    r = Rule(name="t", team="t", match={"min_score": 90})  # type: ignore[arg-type]
    assert not matches(r, lead, ex, s)
    r2 = Rule(name="t", team="t", match={"channel": ["email"], "sensitive": False})  # type: ignore[arg-type]
    assert matches(r2, lead, ex, s)
    rt2, rule2 = route(config, lead, _ex(intent=Intent.other), s)
    assert rule2.name == "default" and rt2.team == "front-desk"


def test_first_matching_rule_wins(config: RoutingConfig) -> None:
    lead = Lead(message="x")
    ex = _ex(intent=Intent.appointment, urgency=Urgency.emergency, location="Lyon")
    _, rule = route(config, lead, ex, score_lead(lead, ex, config.weights))
    assert rule.name == "emergency-any"


def test_agent_auto_replies_only_when_safe(agent: TriageAgent) -> None:
    d = agent.decide(
        Lead(
            name="Claire Martin",
            email="c@example.org",
            phone="+33612345678",
            message="Bonjour, je souhaite prendre rendez-vous à Lyon cette semaine.",
        )
    )
    assert d.action == "auto_reply" and not d.needs_human
    assert d.reply_draft and d.reply_draft.startswith("Bonjour Claire,") and "4 h" in d.reply_draft
    assert d.route.team == "lyon-front-desk"


def test_agent_guardrails_override_rules(agent: TriageAgent) -> None:
    sensitive = agent.decide(
        Lead(
            message="Je prends un traitement médical lourd, je veux un rendez-vous à Lyon",
            phone="+33600000000",
        )
    )
    assert sensitive.action == "assign" and sensitive.needs_human and sensitive.reply_draft is None
    assert any("sensitive" in r for r in sensitive.reasons)

    emergency = agent.decide(
        Lead(message="Urgence, ça saigne beaucoup, rendez-vous à Lyon tout de suite", phone="+33600000000")
    )
    assert emergency.action == "escalate" and emergency.route.team == "on-call" and emergency.needs_human

    vague = agent.decide(Lead(message="Bonjour, je voulais savoir."))
    assert vague.needs_human and vague.route.team == "front-desk"
    assert any("confidence" in r for r in vague.reasons)


def test_agent_tier_threshold_blocks_auto_reply(config: RoutingConfig) -> None:
    config.auto_reply_min_tier = "A"
    agent = TriageAgent(RuleBasedExtractor(), config)
    d = agent.decide(Lead(message="Je souhaite prendre rendez-vous à Lyon", email="x@example.com"))
    assert d.score.tier != "A" and d.action == "assign"
    assert any("below auto-reply threshold" in r for r in d.reasons)


def test_render_template_fills_placeholders_and_defaults() -> None:
    assert (
        render_template("Hi {first_name} from {company} ({sla}h)", Lead(message="x"), sla="4")
        == "Hi there from  (4h)"
    )
    assert render_template("Hi {first_name}", Lead(message="x", name="Jean Dupont")) == "Hi Jean"


def test_audit_log_minimises_pii_and_detects_duplicates(agent: TriageAgent, tmp_path: Path) -> None:
    log = AuditLog(tmp_path / "a" / "audit.jsonl")
    lead = Lead(
        name="Marie Dupont",
        email="marie.dupont@example.com",
        phone="+33612345678",
        message="Un devis svp pour 12 rue des Lilas",
    )
    d = agent.decide(lead)
    assert not log.seen(d.fingerprint)
    log.record(lead, d)
    text = (tmp_path / "a" / "audit.jsonl").read_text()
    assert "m***@example.com" in text
    assert "+33612345678" not in text and "Marie" not in text and "rue des Lilas" not in text
    assert log.seen(d.fingerprint)
