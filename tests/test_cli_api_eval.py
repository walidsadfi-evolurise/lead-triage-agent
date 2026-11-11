from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient
from typer.testing import CliRunner

from triage import api
from triage.cli import app
from triage.evaluate import evaluate, load_cases
from triage.factory import make_agent

ROOT = Path(__file__).resolve().parents[1]


def _settings_env(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("TRIAGE_ROUTING_FILE", str(ROOT / "routing.yaml"))
    monkeypatch.setenv("TRIAGE_AUDIT_FILE", str(tmp_path / "audit.jsonl"))
    monkeypatch.setenv("TRIAGE_LLM_PROVIDER", "rules")
    monkeypatch.setenv("TRIAGE_API_TOKEN", "secret")


def test_demo_evalset_passes(agent) -> None:  # type: ignore[no-untyped-def]
    report = evaluate(agent, load_cases(ROOT / "evalsets" / "demo.yaml"))
    s = report.summary()
    assert s["cases"] == 9 and s["pass_rate"] == 1.0 and s["escalation_recall"] == 1.0


def test_cli_run_and_eval(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    _settings_env(monkeypatch, tmp_path)
    runner = CliRunner()
    r = runner.invoke(app, ["run", str(ROOT / "examples" / "leads.json"), "--json", "--record"])
    assert r.exit_code == 0, r.output
    out = json.loads(r.output)
    assert [d["action"] for d in out] == ["auto_reply", "escalate", "discard"]
    assert (tmp_path / "audit.jsonl").read_text().count("\n") == 3
    r = runner.invoke(app, ["eval", str(ROOT / "evalsets" / "demo.yaml"), "--min-pass-rate", "0.9"])
    assert r.exit_code == 0 and "escalation_recall" in r.output


def test_api_webhook(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    _settings_env(monkeypatch, tmp_path)
    built = make_agent()
    monkeypatch.setattr(api, "deps", lambda: built)
    client = TestClient(api.app)
    assert client.get("/healthz").json()["extractor"] == "rules"
    lead = {
        "name": "Claire",
        "email": "c@example.org",
        "phone": "+33612345678",
        "message": "Rendez-vous à Lyon cette semaine svp",
    }
    assert client.post("/leads", json=lead).status_code == 401
    h = {"authorization": "Bearer secret"}
    r = client.post("/leads", json=lead, headers=h)
    assert r.status_code == 200 and r.json()["action"] == "auto_reply"
    assert client.post("/leads", json=lead, headers=h).status_code == 409  # duplicate
    assert client.post("/leads?dry_run=true", json=lead, headers=h).status_code == 200
    assert client.post("/leads", json={"message": ""}, headers=h).status_code == 422


def _form_client(monkeypatch, tmp_path: Path, origins: str = "https://example.com") -> TestClient:  # type: ignore[no-untyped-def]
    _settings_env(monkeypatch, tmp_path)
    monkeypatch.setenv("TRIAGE_FORM_ORIGINS", origins)
    built = make_agent()
    monkeypatch.setattr(api, "deps", lambda: built)
    rl = api.RateLimiter(limit=3, window_seconds=600)
    monkeypatch.setattr(api, "limiter", lambda: rl)
    return TestClient(api.app)


def test_public_form(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    sent: list[dict] = []  # type: ignore[type-arg]
    monkeypatch.setenv("TRIAGE_NOTIFY_URL", "https://hooks.example.com/x")
    monkeypatch.setattr(api, "notify", lambda url, token, payload: sent.append(payload))
    client = _form_client(monkeypatch, tmp_path)
    body = {
        "name": "Claire",
        "email": "c@example.org",
        "phone": "+33612345678",
        "message": "Rendez-vous à Lyon cette semaine svp",
        "page": "/contact/",
    }
    # wrong or missing origin: refused, no CORS header
    assert client.post("/forms/site", json=body).status_code == 403
    assert (
        client.post("/forms/site", json=body, headers={"origin": "https://evil.example"}).status_code == 403
    )
    # preflight
    pre = client.options("/forms/site", headers={"origin": "https://example.com"})
    assert pre.status_code == 204 and pre.headers["access-control-allow-origin"] == "https://example.com"
    # real submission: thin receipt, CORS header, audit line, notification with the full decision
    r = client.post("/forms/site", json=body, headers={"origin": "https://example.com/"})
    assert r.status_code == 200, r.text
    receipt = r.json()
    assert set(receipt) == {"status", "reference", "sla_hours", "next"}
    assert receipt["next"] == "reply" and receipt["sla_hours"] == 4
    assert r.headers["access-control-allow-origin"] == "https://example.com"
    assert (tmp_path / "audit.jsonl").read_text().count("\n") == 1
    assert len(sent) == 1 and sent[0]["decision"]["action"] == "auto_reply" and sent[0]["form"] == "site"
    # double submit: same reference, nothing new recorded or sent
    r2 = client.post("/forms/site", json=body, headers={"origin": "https://example.com"})
    assert r2.json()["reference"] == receipt["reference"]
    assert (tmp_path / "audit.jsonl").read_text().count("\n") == 1 and len(sent) == 1
    # honeypot: looks like a success, processes nothing
    bot = client.post(
        "/forms/site",
        json={**body, "message": "buy now", "website": "http://spam"},
        headers={"origin": "https://example.com"},
    )
    assert bot.status_code == 202 and bot.json()["reference"] == "ok"
    assert (tmp_path / "audit.jsonl").read_text().count("\n") == 1
    # rate limit: 3 per window for this IP (two real posts above already counted)
    client.post(
        "/forms/site", json={**body, "message": "another question"}, headers={"origin": "https://example.com"}
    )
    r4 = client.post(
        "/forms/site", json={**body, "message": "yet another"}, headers={"origin": "https://example.com"}
    )
    assert r4.status_code == 429


def test_public_form_disabled_by_default(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    client = _form_client(monkeypatch, tmp_path, origins="")
    r = client.post("/forms/site", json={"message": "hello"}, headers={"origin": "https://example.com"})
    assert r.status_code == 404


def test_rate_limiter_window() -> None:
    rl = api.RateLimiter(limit=2, window_seconds=10)
    assert rl.allow("a", now=0.0) and rl.allow("a", now=1.0)
    assert not rl.allow("a", now=2.0)
    assert rl.allow("b", now=2.0)  # other key unaffected
    assert rl.allow("a", now=11.5)  # window slid
