"""Unit tests of the fake inbound-line directory (I07): the number and the account must both
match, and a receipt is found by its account alone."""

import pytest

from diucs.adapters.testing.fixed_inbound_lines import FixedInboundLines
from diucs.application.ports.outbound.tenant_lines import InboundLine

LINE_A = InboundLine("tenant-a", "twilio/tenant-a")
LINE_B = InboundLine("tenant-b", "twilio/tenant-b")
NUMBER_A = "+447700900001"
NUMBER_B = "+447700900002"
ACCOUNT_A = "AC" + "a" * 32
ACCOUNT_B = "AC" + "b" * 32


def _lines() -> FixedInboundLines:
    return FixedInboundLines([(NUMBER_A, ACCOUNT_A, LINE_A), (NUMBER_B, ACCOUNT_B, LINE_B)])


async def test_a_number_and_its_account_find_the_line() -> None:
    assert await _lines().for_number(NUMBER_A, ACCOUNT_A) == LINE_A
    assert await _lines().for_number(NUMBER_B, ACCOUNT_B) == LINE_B


async def test_a_number_under_another_account_is_not_found() -> None:
    assert await _lines().for_number(NUMBER_A, ACCOUNT_B) is None
    assert await _lines().for_number(NUMBER_B, ACCOUNT_A) is None


async def test_an_unknown_number_or_account_is_not_found() -> None:
    assert await _lines().for_number("+447700900009", ACCOUNT_A) is None
    assert await _lines().for_number(NUMBER_A, "AC" + "c" * 32) is None


async def test_an_account_finds_its_line_and_an_unknown_account_finds_none() -> None:
    assert await _lines().for_account(ACCOUNT_A) == LINE_A
    assert await _lines().for_account(ACCOUNT_B) == LINE_B
    assert await _lines().for_account("AC" + "c" * 32) is None


async def test_one_account_may_hold_two_numbers_of_the_same_tenant() -> None:
    lines = FixedInboundLines([(NUMBER_A, ACCOUNT_A, LINE_A), (NUMBER_B, ACCOUNT_A, LINE_A)])
    assert await lines.for_number(NUMBER_B, ACCOUNT_A) == LINE_A
    assert await lines.for_account(ACCOUNT_A) == LINE_A


def test_one_account_for_two_tenants_is_refused_when_the_fake_is_built() -> None:
    with pytest.raises(ValueError, match="one tenant"):
        FixedInboundLines([(NUMBER_A, ACCOUNT_A, LINE_A), (NUMBER_B, ACCOUNT_A, LINE_B)])
