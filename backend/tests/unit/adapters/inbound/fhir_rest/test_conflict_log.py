"""A 409 says nothing about which rule refused, so the API logs the rule's phrase (the domain keeps
every value out of its messages). The answer to the caller stays the one fixed text."""

import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from overwatch.adapters.inbound.fhir_rest.errors import CONFLICT_TEXT, install_exception_handlers
from overwatch.domain.errors import Conflict


def _client() -> TestClient:
    app = FastAPI()
    install_exception_handlers(app)

    @app.post("/clash")
    def clash() -> None:
        raise Conflict("that group already gives another role")

    return TestClient(app, raise_server_exceptions=False)


def test_a_conflict_is_logged_with_its_rule_and_answered_with_the_fixed_text(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)

    response = _client().post("/clash")

    assert response.status_code == 409
    assert CONFLICT_TEXT in response.text
    assert "conflict: that group already gives another role" in caplog.text
    assert "another role" not in response.text
