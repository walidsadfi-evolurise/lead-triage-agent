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
    api.deps.cache_clear()
    api.deps = lambda: make_agent()  # type: ignore[assignment]
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
