from __future__ import annotations

from pathlib import Path

import pytest

from boomi_solace_migration.models import ConnectorProfile, NamingPolicy

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def connector_profile() -> ConnectorProfile:
    return ConnectorProfile.from_yaml(ROOT / "examples/connector-profile.example.yaml")


@pytest.fixture
def naming_policy() -> NamingPolicy:
    return NamingPolicy.from_yaml(ROOT / "examples/naming-policy.example.yaml")


@pytest.fixture
def fixture_dir() -> Path:
    return ROOT / "tests/fixtures"
