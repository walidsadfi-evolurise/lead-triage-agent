# Security

Report vulnerabilities privately to walid.sadfi@evolurise.com. Acknowledgement within 72 hours.

Operating notes:

- Set `TRIAGE_API_TOKEN`; the webhook is open otherwise.
- The audit log stores masked emails and no phone numbers or message bodies by design; keep it that way if you extend it.
- Lead text is sent to the configured LLM provider. For regulated data, point `TRIAGE_LLM_BASE_URL` at a self-hosted OpenAI-compatible model or keep `TRIAGE_LLM_PROVIDER=rules`.
- Reply drafts are template-based and never generated for sensitive or emergency leads.
