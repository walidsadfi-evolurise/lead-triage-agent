"""The decision pipeline: extract → score → route → guardrails → (draft reply)."""

from __future__ import annotations

from datetime import UTC, datetime

from triage.extract import Extractor
from triage.models import Decision, Intent, Lead, Urgency
from triage.routing import RoutingConfig, route
from triage.scoring import score_lead


def render_template(template: str, lead: Lead, **extra: str) -> str:
    first = (lead.name or "").split(" ")[0] if lead.name else ""
    values = {"first_name": first or "there", "name": lead.name or "", "company": lead.company or "", **extra}
    out = template
    for k, v in values.items():
        out = out.replace("{" + k + "}", v)
    return out


class TriageAgent:
    def __init__(self, extractor: Extractor, config: RoutingConfig) -> None:
        self.extractor = extractor
        self.config = config

    def decide(self, lead: Lead) -> Decision:
        ex = self.extractor.extract(lead)
        score = score_lead(lead, ex, self.config.weights)
        rt, rule = route(self.config, lead, ex, score)
        reasons: list[str] = [
            f"rule '{rule.name}' → team {rt.team}",
            f"score {score.total} (tier {score.tier})",
        ]
        action = rule.action
        needs_human = False

        # Guardrails — these override whatever the rule said.
        if ex.sensitive:
            needs_human = True
            if action == "auto_reply":
                action = "assign"
            reasons.append("sensitive content: no automatic reply")
        if ex.urgency is Urgency.emergency:
            needs_human = True
            action = "escalate"
            reasons.append("emergency: escalated to a human now")
        if ex.confidence < self.config.needs_human_below_confidence and action != "discard":
            needs_human = True
            if action == "auto_reply":
                action = "assign"
            reasons.append(f"low extraction confidence ({ex.confidence:.2f}): human review")
        if action == "auto_reply" and score.tier > self.config.auto_reply_min_tier:
            action = "assign"
            reasons.append(f"tier {score.tier} below auto-reply threshold {self.config.auto_reply_min_tier}")
        if ex.intent is Intent.spam and action != "discard":
            action = "discard"
            reasons.append("classified as spam")

        draft = None
        if action == "auto_reply" and rule.reply_template:
            tpl = self.config.templates.get(rule.reply_template, rule.reply_template)
            draft = render_template(tpl, lead, service=ex.service or "", sla=str(rt.sla_hours))

        return Decision(
            lead_id=lead.lead_id or lead.fingerprint(),
            fingerprint=lead.fingerprint(),
            extraction=ex,
            score=score,
            route=rt,
            action=action,  # type: ignore[arg-type]
            needs_human=needs_human,
            reasons=reasons,
            reply_draft=draft,
            decided_at=datetime.now(UTC),
            model=self.extractor.name,
        )
