"""Append-only JSONL audit log with PII minimisation.

The log keeps what you need to answer "why did the agent do that?" six months
later — and not the customer's phone number.
"""

from __future__ import annotations

import json
from pathlib import Path

from triage.models import Decision, Lead


def _mask_email(email: str | None) -> str | None:
    if not email or "@" not in email:
        return None
    user, domain = email.split("@", 1)
    return f"{user[:1]}***@{domain}"


class AuditLog:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, lead: Lead, decision: Decision) -> None:
        entry = {
            "lead_id": decision.lead_id,
            "fingerprint": decision.fingerprint,
            "received_at": lead.received_at.isoformat(),
            "decided_at": decision.decided_at.isoformat(),
            "channel": lead.channel.value,
            "source": lead.source,
            "email": _mask_email(lead.email),
            "has_phone": bool(lead.phone),
            "company": lead.company,
            "extraction": decision.extraction.model_dump(mode="json"),
            "score": decision.score.model_dump(mode="json"),
            "route": decision.route.model_dump(mode="json"),
            "action": decision.action,
            "needs_human": decision.needs_human,
            "reasons": decision.reasons,
            "model": decision.model,
        }
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def seen(self, fingerprint: str) -> bool:
        if not self.path.exists():
            return False
        with self.path.open(encoding="utf-8") as fh:
            return any(json.loads(line).get("fingerprint") == fingerprint for line in fh if line.strip())
