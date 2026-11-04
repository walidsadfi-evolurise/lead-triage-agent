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
