"""One `number_after_prompt` for the text and the link, and public names for what RenewLink reuses
(KI-159, KI-160).

The text reply (HandleInboundText) and the link reply (link_access) both judge hazard H-32 (a number
written since the prompt was sent). They each had a copy; the copies could drift. They now share
`diucs.application.prompt_judgement`. RenewLink imported the private `_render` and `_send_payload`
of send_prompts; the names it reuses are public now.
"""

import ast
import inspect
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from diucs.application import prompt_judgement
from diucs.application.use_cases import handle_inbound_text, link_access, send_prompts
from diucs.domain.codes import Measure, ReportSource, ReportType
from diucs.domain.model.capacity import CapacityReport

PROMPT = datetime(2026, 10, 23, 9, 0, 30, 400000, tzinfo=UTC)


def _report(
    report_type: ReportType = ReportType.NUMBER,
    *,
    written_at: datetime | None,
    effective_at: datetime = PROMPT - timedelta(hours=1),
) -> CapacityReport:
    return CapacityReport(
        id="r",
        service_id="svc",
        value=3,
        measure=Measure.REFERRALS_ACCEPTABLE,
        effective_at=effective_at,
        source=ReportSource.TEXT,
        report_type=report_type,
        written_at=written_at,
    )


class _Capacity:
    def __init__(self, since: list[CapacityReport]) -> None:
        self._since = since

    async def reports_since(self, service_id: str, since: datetime) -> list[CapacityReport]:
        return self._since


def _uow(since: list[CapacityReport]) -> Any:
    return SimpleNamespace(capacity=_Capacity(since))


# --- one function, used by both ------------------------------------------------------------------


def test_the_text_and_the_link_use_the_same_functions() -> None:
    assert link_access.number_after_prompt is prompt_judgement.number_after_prompt
    assert handle_inbound_text.number_after_prompt is prompt_judgement.number_after_prompt
    assert handle_inbound_text.recorded_since_prompt is prompt_judgement.recorded_since_prompt
    assert handle_inbound_text.figure_is_out_of_date is prompt_judgement.figure_is_out_of_date


def test_neither_module_defines_its_own_copy() -> None:
    for module in (link_access, handle_inbound_text):
        tree = ast.parse(inspect.getsource(module))
        defined = {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        }
        assert "number_after_prompt" not in defined
        assert "_number_after_prompt" not in defined
        assert "recorded_since_prompt" not in defined
        assert "figure_is_out_of_date" not in defined


# --- the shared behaviour (H-32), at its boundaries ----------------------------------------------


async def test_a_number_written_after_the_prompt_counts() -> None:
    later = _report(written_at=PROMPT + timedelta(seconds=5))

    assert await prompt_judgement.number_after_prompt(_uow([later]), "svc", None, PROMPT) is True


async def test_a_number_written_in_the_prompts_own_second_counts() -> None:
    # The store stamps whole seconds, so a tie fails closed (DEC-148).
    same_second = _report(written_at=PROMPT.replace(microsecond=0))

    assert (
        await prompt_judgement.number_after_prompt(_uow([same_second]), "svc", None, PROMPT) is True
    )


async def test_a_number_written_a_second_before_the_prompts_second_does_not_count() -> None:
    before = _report(written_at=PROMPT.replace(microsecond=0) - timedelta(seconds=1))

    assert await prompt_judgement.number_after_prompt(_uow([]), "svc", before, PROMPT) is False


async def test_a_confirmation_written_after_the_prompt_does_not_count() -> None:
    confirmation = _report(ReportType.CONFIRMED, written_at=PROMPT + timedelta(minutes=1))

    assert (
        await prompt_judgement.number_after_prompt(
            _uow([confirmation]), "svc", confirmation, PROMPT
        )
        is False
    )


async def test_the_latest_report_is_looked_at_too_and_may_be_absent() -> None:
    later = _report(written_at=PROMPT + timedelta(seconds=5))

    assert await prompt_judgement.number_after_prompt(_uow([]), "svc", later, PROMPT) is True
    assert await prompt_judgement.number_after_prompt(_uow([]), "svc", None, PROMPT) is False


async def test_a_report_with_no_write_time_cannot_be_shown_to_predate_the_prompt() -> None:
    unknown = _report(written_at=None)

    assert await prompt_judgement.number_after_prompt(_uow([]), "svc", unknown, PROMPT) is True


def test_a_figure_is_out_of_date_only_when_strictly_older_than_the_window() -> None:
    window = prompt_judgement.CONFIRMABLE_FIGURE_AGE

    assert prompt_judgement.figure_is_out_of_date(PROMPT - window, PROMPT) is False
    assert (
        prompt_judgement.figure_is_out_of_date(PROMPT - window - timedelta(microseconds=1), PROMPT)
        is True
    )
    assert prompt_judgement.figure_is_out_of_date(PROMPT + timedelta(hours=1), PROMPT) is False


# --- KI-160: RenewLink reuses public names --------------------------------------------------------


def test_renew_link_imports_no_private_name_of_send_prompts() -> None:
    tree = ast.parse(inspect.getsource(link_access))
    names = [
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == send_prompts.__name__
        for alias in node.names
    ]

    assert names
    assert [name for name in names if name.startswith("_")] == []


@pytest.mark.parametrize("name", ["render_prompt", "send_payload"])
def test_send_prompts_publishes_the_names_others_reuse(name: str) -> None:
    assert callable(getattr(send_prompts, name))


def test_the_private_names_still_answer_for_the_tests_that_use_them() -> None:
    assert send_prompts._render is send_prompts.render_prompt
    assert send_prompts._send_payload is send_prompts.send_payload
