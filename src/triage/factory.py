from __future__ import annotations

from pathlib import Path

from triage.agent import TriageAgent
from triage.audit import AuditLog
from triage.config import Settings
from triage.extract import Extractor, LLMExtractor, RuleBasedExtractor
from triage.llm import AnthropicLLM, OpenAICompatibleLLM
from triage.routing import RoutingConfig


def make_extractor(s: Settings) -> Extractor:
    if s.llm_provider == "rules":
        return RuleBasedExtractor()
    if s.llm_provider == "anthropic":
        if not s.anthropic_api_key:
            raise ValueError("TRIAGE_ANTHROPIC_API_KEY is required")
        return LLMExtractor(AnthropicLLM(s.llm_model, s.anthropic_api_key))
    if s.llm_provider == "openai":
        return LLMExtractor(OpenAICompatibleLLM(s.llm_model, s.llm_base_url, s.openai_api_key))
    raise ValueError(f"unknown provider {s.llm_provider}")


def make_agent(s: Settings | None = None) -> tuple[TriageAgent, AuditLog, Settings]:
    s = s or Settings()
    cfg = RoutingConfig.load(Path(s.routing_file))
    return TriageAgent(make_extractor(s), cfg), AuditLog(Path(s.audit_file)), s
