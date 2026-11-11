from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TRIAGE_", env_file=".env", extra="ignore")

    routing_file: str = "routing.yaml"
    audit_file: str = "data/audit.jsonl"
    llm_provider: str = "rules"  # rules | anthropic | openai
    llm_model: str = "claude-haiku-4-5"
    llm_base_url: str = "https://api.openai.com/v1"
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None
    api_token: str | None = None
    dedupe: bool = True

    # Public website forms (POST /forms/{form_id}). Disabled until at least one origin is listed.
    form_origins: str = ""  # comma-separated, e.g. "https://example.com,https://www.example.com"
    form_rate_limit: int = 5  # submissions per client IP per window
    form_rate_window_seconds: int = 600
    turnstile_secret: str | None = None  # Cloudflare Turnstile server key; verified when set
    notify_url: str | None = None  # POST every form decision here (Slack, n8n, your CRM…)
    notify_token: str | None = None  # sent as Bearer to notify_url

    @property
    def allowed_form_origins(self) -> frozenset[str]:
        return frozenset(o.strip().rstrip("/") for o in self.form_origins.split(",") if o.strip())
