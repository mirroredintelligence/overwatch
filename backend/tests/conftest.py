"""Shared pytest hooks. Fixtures for Neo4j arrive with F10 in tests/support/."""

from pathlib import Path

import pytest

_INTEGRATION_ROOT = Path(__file__).resolve().parent / "integration"


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Mark everything under tests/integration/ so it can be selected or skipped by marker."""
    for item in items:
        if Path(str(item.path)).resolve().is_relative_to(_INTEGRATION_ROOT):
            item.add_marker(pytest.mark.integration)
