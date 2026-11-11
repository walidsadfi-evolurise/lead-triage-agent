"""HTTP surface.

- ``POST /leads``            authenticated webhook for your CRM / mailbox / automation (full decision back)
- ``POST /forms/{form_id}``  public endpoint a static website form can call directly: origin allow-list,
                             honeypot, per-IP rate limit, optional Cloudflare Turnstile, and a receipt that
                             exposes nothing about routing or scoring. Decisions are audited and, if
                             ``TRIAGE_NOTIFY_URL`` is set, forwarded to your own system.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict, deque
from functools import lru_cache
from typing import Annotated, Any, Literal

import httpx
from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr, Field

from triage.agent import TriageAgent
from triage.audit import AuditLog
from triage.config import Settings
from triage.factory import make_agent
from triage.models import Channel, Decision, Lead

log = logging.getLogger("triage.api")

app = FastAPI(title="lead-triage-agent", version="0.2.0")


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


# ----------------------------------------------------------------------------- public forms ---


class FormSubmission(BaseModel):
    """What a website form posts. ``website`` is a honeypot: humans never see it, bots fill it."""

    name: str | None = Field(default=None, max_length=200)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=40)
    company: str | None = Field(default=None, max_length=200)
    message: str = Field(min_length=1, max_length=20_000)
    page: str | None = Field(default=None, max_length=500, description="URL or path the form sits on")
    website: str = Field(default="", description="Honeypot; must stay empty")
    turnstile_token: str | None = Field(default=None, max_length=4096)


class FormReceipt(BaseModel):
    """Deliberately thin: no team, score, tier or reasons leave the server through a public endpoint."""

    status: Literal["received"] = "received"
    reference: str
    sla_hours: int | None = None
    next: Literal["reply", "human"] = "human"


class RateLimiter:
    """Sliding window per key, in memory. One replica is the normal deployment for a website form;
    put a reverse-proxy limit in front if you run several."""

    def __init__(self, limit: int, window_seconds: int) -> None:
        self.limit, self.window = limit, window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] > self.window:
                q.popleft()
            if len(q) >= self.limit:
                return False
            q.append(now)
            return True


@lru_cache(maxsize=1)
def limiter() -> RateLimiter:
    s = deps()[2]
    return RateLimiter(s.form_rate_limit, s.form_rate_window_seconds)


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _cors(response: Response, origin: str) -> None:
    response.headers["access-control-allow-origin"] = origin
    response.headers["access-control-allow-methods"] = "POST, OPTIONS"
    response.headers["access-control-allow-headers"] = "content-type"
    response.headers["access-control-max-age"] = "600"
    response.headers["vary"] = "Origin"


def _check_origin(request: Request) -> str:
    s = deps()[2]
    allowed = s.allowed_form_origins
    if not allowed:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "public forms are not enabled (TRIAGE_FORM_ORIGINS)")
    origin = (request.headers.get("origin") or "").rstrip("/")
    if origin not in allowed:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "origin not allowed")
    return origin


def verify_turnstile(secret: str, token: str | None, ip: str) -> bool:
    if not token:
        return False
    try:
        r = httpx.post(
            "https://challenges.cloudflare.com/turnstile/v0/siteverify",
            data={"secret": secret, "response": token, "remoteip": ip},
            timeout=5.0,
        )
        return bool(r.json().get("success"))
    except (httpx.HTTPError, ValueError):  # network or non-JSON answer: fail closed
        return False


def notify(url: str, token: str | None, payload: dict[str, Any]) -> None:
    """Forward a decision to the owner's system. Best effort: a notification failure never loses the lead,
    which is already in the audit log."""
    headers = {"authorization": f"Bearer {token}"} if token else {}
    try:
        httpx.post(url, json=payload, headers=headers, timeout=5.0).raise_for_status()
    except httpx.HTTPError as exc:
        log.warning("notify failed: %s", exc)


@app.options("/forms/{form_id}")
def form_preflight(form_id: str, request: Request) -> Response:
    origin = _check_origin(request)
    resp = Response(status_code=status.HTTP_204_NO_CONTENT)
    _cors(resp, origin)
    return resp


@app.post("/forms/{form_id}", response_model=FormReceipt)
def submit_form(
    form_id: str, body: FormSubmission, request: Request, response: Response, tasks: BackgroundTasks
) -> FormReceipt:
    origin = _check_origin(request)
    _cors(response, origin)
    agent, audit, s = deps()
    ip = client_ip(request)

    if body.website:  # honeypot: answer like a success so the bot learns nothing
        log.info("form %s: honeypot hit from %s", form_id, ip)
        response.status_code = status.HTTP_202_ACCEPTED
        return FormReceipt(reference="ok")

    if not limiter().allow(ip):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "too many submissions, try again later")

    if s.turnstile_secret and not verify_turnstile(s.turnstile_secret, body.turnstile_token, ip):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "human verification failed")

    lead = Lead(
        channel=Channel.form,
        name=body.name,
        email=body.email,
        phone=body.phone,
        company=body.company,
        message=body.message,
        source=body.page or form_id,
        extra={"form": form_id, "origin": origin},
    )
    fp = lead.fingerprint()
    if s.dedupe and audit.seen(fp):  # double submit: same receipt, no second decision or notification
        return FormReceipt(reference=fp[:8])

    decision = agent.decide(lead)
    audit.record(lead, decision)
    if s.notify_url:
        tasks.add_task(
            notify,
            s.notify_url,
            s.notify_token,
            {
                "form": form_id,
                "lead": lead.model_dump(mode="json"),
                "decision": decision.model_dump(mode="json"),
            },
        )
    return FormReceipt(
        reference=fp[:8],
        sla_hours=decision.route.sla_hours if decision.action != "discard" else None,
        next="reply" if decision.action == "auto_reply" else "human",
    )
