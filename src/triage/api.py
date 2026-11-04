"""Webhook: POST /leads with the raw lead → decision. Wire your form / CRM / mailbox to it."""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, status

from triage.agent import TriageAgent
from triage.audit import AuditLog
from triage.config import Settings
from triage.factory import make_agent
from triage.models import Decision, Lead

app = FastAPI(title="lead-triage-agent", version="0.1.0")


@lru_cache(maxsize=1)
def deps() -> tuple[TriageAgent, AuditLog, Settings]:
    return make_agent()


def require_token(authorization: Annotated[str | None, Header()] = None) -> None:
    token = deps()[2].api_token
    if token and authorization != f"Bearer {token}":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or missing bearer token")


@app.get("/healthz")
def healthz() -> dict[str, str]:
    agent, _, s = deps()
    return {"status": "ok", "extractor": agent.extractor.name, "rules": str(len(agent.config.rules))}


@app.post("/leads", response_model=Decision, dependencies=[Depends(require_token)])
def triage_lead(lead: Lead, dry_run: bool = False) -> Decision:
    agent, audit, s = deps()
    if s.dedupe and not dry_run and audit.seen(lead.fingerprint()):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "duplicate lead (same contact and message already processed)"
        )
    decision = agent.decide(lead)
    if not dry_run:
        audit.record(lead, decision)
    return decision
