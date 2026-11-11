# Changelog

## 0.2.0 — 2026-11-11

- `POST /forms/{form_id}`: public endpoint for static website forms — origin allow-list with CORS, honeypot, per-IP sliding-window rate limit, optional Cloudflare Turnstile verification, thin receipt (reference, SLA, next step) that exposes no routing or scoring, dedupe of double submits, background notification of the full decision to `TRIAGE_NOTIFY_URL`.
- Settings: `TRIAGE_FORM_ORIGINS`, `TRIAGE_FORM_RATE_LIMIT`, `TRIAGE_FORM_RATE_WINDOW_SECONDS`, `TRIAGE_TURNSTILE_SECRET`, `TRIAGE_NOTIFY_URL`, `TRIAGE_NOTIFY_TOKEN`.

## 0.1.0 — 2026-11-04

- Lead / Extraction / Score / Route / Decision contracts (pydantic).
- LLM extraction with strict JSON validation and rule-based fallback; Anthropic and OpenAI-compatible clients.
- Explainable scoring with YAML weights and tiers.
- Declarative first-match routing; guardrails for emergencies, sensitive content, low confidence, spam.
- Audit log with PII minimisation and deduplication.
- `triage run | eval | serve`, FastAPI webhook with bearer auth, Docker image, eval set used as a CI gate.
