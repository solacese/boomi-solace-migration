from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def producer_xml() -> str:
    return (FIXTURES / "producer.xml").read_text(encoding="utf-8")


@pytest.fixture
def consumer_xml() -> str:
    return (FIXTURES / "consumer.xml").read_text(encoding="utf-8")
