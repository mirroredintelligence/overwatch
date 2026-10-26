"""The integration marker is registered, so a contract factory can carry it (DEC-077)."""

import pytest


def test_the_integration_marker_is_registered(pytestconfig: pytest.Config) -> None:
    markers = pytestconfig.getini("markers")
    assert any(line.startswith("integration:") for line in markers)
