"""How the support routes answer a refusal (R18): the two 403s this module owns, the telemetry
outage, and every other refusal left to the app's non-revealing 404. No database: the use cases are
not run here."""

import json

import pytest
from fastapi.responses import Response

from diucs.adapters.inbound.fhir_rest.routes_support import (
    CODE_REFUSED_TEXT,
    EVENTS_REFUSED_TEXT,
    TELEMETRY_UNAVAILABLE_TEXT,
    _answer,
)
from diucs.application.ports.outbound.telemetry_query import TelemetryUnavailable
from diucs.application.use_cases.support_access import OPEN_REFUSED, ROLE_REFUSED
from diucs.application.use_cases.support_console import EVENTS_REFUSED
from diucs.domain.errors import NotAllowed


def _body(response: Response) -> dict[str, object]:
    return json.loads(bytes(response.body))


async def _raising(error: Exception) -> Response:
    raise error


async def test_a_wrong_or_expired_code_is_a_403_with_the_one_message() -> None:
    response = await _answer(lambda: _raising(NotAllowed(OPEN_REFUSED)))

    assert response.status_code == 403
    assert CODE_REFUSED_TEXT in json.dumps(_body(response))


async def test_a_session_that_is_not_open_to_the_caller_is_a_403() -> None:
    response = await _answer(lambda: _raising(NotAllowed(EVENTS_REFUSED)))

    assert response.status_code == 403
    assert EVENTS_REFUSED_TEXT in json.dumps(_body(response))


async def test_a_role_refusal_is_left_to_the_app_and_answers_404() -> None:
    with pytest.raises(NotAllowed):
        await _answer(lambda: _raising(NotAllowed(ROLE_REFUSED)))


async def test_a_telemetry_outage_is_a_fixed_503_that_names_no_detail() -> None:
    response = await _answer(lambda: _raising(TelemetryUnavailable()))

    assert response.status_code == 503
    assert TELEMETRY_UNAVAILABLE_TEXT in json.dumps(_body(response))


async def test_a_successful_answer_passes_through_unchanged() -> None:
    expected = Response(status_code=204)

    async def run() -> Response:
        return expected

    assert await _answer(run) is expected
