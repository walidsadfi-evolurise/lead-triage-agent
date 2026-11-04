# Changelog

## 0.1.0 — 2026-11-04

- Lead / Extraction / Score / Route / Decision contracts (pydantic).
- LLM extraction with strict JSON validation and rule-based fallback; Anthropic and OpenAI-compatible clients.
- Explainable scoring with YAML weights and tiers.
- Declarative first-match routing; guardrails for emergencies, sensitive content, low confidence, spam.
- Audit log with PII minimisation and deduplication.
- `triage run | eval | serve`, FastAPI webhook with bearer auth, Docker image, eval set used as a CI gate.
