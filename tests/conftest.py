from __future__ import annotations

from pathlib import Path

import pytest

from triage.agent import TriageAgent
from triage.extract import RuleBasedExtractor
from triage.routing import RoutingConfig

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def config() -> RoutingConfig:
    return RoutingConfig.load(ROOT / "routing.yaml")


@pytest.fixture
def agent(config: RoutingConfig) -> TriageAgent:
    return TriageAgent(RuleBasedExtractor(), config)
