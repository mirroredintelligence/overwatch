"""PreviewPairing (TEN-072, WB11): the lead's look at a code before connecting a screen.

The confirm step of pairing (docs/design/network-ui.md section 6, ScreenClaim) shows when the
screen first asked for its code and what kind of device it is. The read burns nothing and writes
nothing, it counts a refused code against the same failure allowance as a connect (so it cannot be
used to guess codes), and every refusal is the one NotAllowed of pairing. Synthetic values only.
"""

from dataclasses import replace
from datetime import timedelta

import pytest
import pytest_asyncio
from neo4j import AsyncDriver

from diucs.adapters.outbound.audit_neo4j.audit_log import ensure_audit_head
from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.use_cases.pair_wall_screen import (
    REFUSED_MESSAGE,
    PairingPreview,
    PairingRateLimited,
    PreviewPairing,
)
from diucs.domain.errors import NotAllowed
from tests.integration.application.test_pair_wall_screen import (
    ADVISOR,
    LEAD,
    SECRETS,
    Rig,
    _command,
    _state,
    make_rig,
)
from tests.support.neo4j import count_nodes_run

pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest_asyncio.fixture(autouse=True, loop_scope="session")
async def fresh_graph(neo4j_driver: AsyncDriver, clean_graph: None) -> None:
    """Wipes the module's own container before each test."""


@pytest_asyncio.fixture(loop_scope="session")
async def rig(
    uow_factory: UnitOfWorkFactory, uow_clock: Clock, neo4j_driver: AsyncDriver, clean_graph: None
) -> Rig:
    await ensure_audit_head(neo4j_driver)
    return make_rig(uow_factory, uow_clock)


def _preview(rig: Rig) -> PreviewPairing:
    return PreviewPairing(rig.uow_factory, rig.clock, FixedSecretStore(SECRETS), rig.cache)


async def test_a_live_code_shows_when_the_screen_first_asked_and_the_device_class(
    rig: Rig,
) -> None:
    started = await rig.start.execute()
    first_seen = rig.clock.now()
    rig.clock.advance(timedelta(minutes=3))
    preview = await _preview(rig).execute(LEAD, started.code_display)
    assert preview == PairingPreview(first_seen_at=first_seen, device_class="wall-display")


async def test_a_code_typed_with_a_space_a_hyphen_or_none_previews_alike(rig: Rig) -> None:
    started = await rig.start.execute()
    digits = started.code_display.replace(" ", "")
    results = {
        await _preview(rig).execute(LEAD, text)
        for text in (started.code_display, f"{digits[:3]}-{digits[3:]}", digits)
    }
    assert len(results) == 1


async def test_a_preview_burns_nothing_and_writes_nothing(
    rig: Rig, neo4j_driver: AsyncDriver
) -> None:
    started = await rig.start.execute()
    before = await _state(neo4j_driver)
    await _preview(rig).execute(LEAD, started.code_display)
    await _preview(rig).execute(LEAD, started.code_display)
    assert await _state(neo4j_driver) == before
    # The code is still good: the lead can connect it after looking.
    confirmed = await rig.confirm.execute(_command(started))
    assert confirmed.screen_name


async def test_every_refusal_is_the_one_not_allowed(rig: Rig, neo4j_driver: AsyncDriver) -> None:
    expired = await rig.start.execute()
    used = await rig.start.execute()
    await rig.confirm.execute(_command(used, key="used-1"))
    rig.clock.advance(timedelta(minutes=10))
    fresh = await rig.start.execute()
    never = "000 000" if fresh.code_display != "000 000" else "111 111"
    before = await _state(neo4j_driver)
    messages: set[str] = set()
    codes = (never, expired.code_display, used.code_display, "48291", "abc def", "")
    for n, code in enumerate(codes):
        # One lead each, so the failure allowance of one lead does not answer for the others.
        lead = replace(LEAD, practitioner_id=f"prac-lead-{n}")
        with pytest.raises(NotAllowed) as refused:
            await _preview(rig).execute(lead, code)
        assert type(refused.value) is NotAllowed
        messages.add(str(refused.value))
    assert messages == {REFUSED_MESSAGE}
    assert await _state(neo4j_driver) == before


async def test_a_code_past_ten_minutes_is_refused(rig: Rig) -> None:
    started = await rig.start.execute()
    rig.clock.advance(timedelta(minutes=10))
    with pytest.raises(NotAllowed):
        await _preview(rig).execute(LEAD, started.code_display)


async def test_only_a_lead_may_preview_and_the_code_is_not_looked_at_otherwise(
    rig: Rig, neo4j_driver: AsyncDriver
) -> None:
    started = await rig.start.execute()
    with pytest.raises(NotAllowed):
        await _preview(rig).execute(ADVISOR, started.code_display)
    # The refusal of a role took no slot of the failure allowance and left the code unburned.
    assert await count_nodes_run(neo4j_driver, "Device") == 0
    assert await _preview(rig).execute(LEAD, started.code_display)


async def test_wrong_codes_use_the_same_allowance_as_a_connect(rig: Rig) -> None:
    """Five wrong codes (previews and connects together) and then every code is refused as rate
    limited, even the right one: a preview is not a way to guess a code."""
    started = await rig.start.execute()
    wrong = "000 000" if started.code_display != "000 000" else "111 111"
    for _ in range(5):
        with pytest.raises(NotAllowed):
            await _preview(rig).execute(LEAD, wrong)
    with pytest.raises(PairingRateLimited):
        await _preview(rig).execute(LEAD, started.code_display)
    with pytest.raises(PairingRateLimited):
        await rig.confirm.execute(_command(started, key="late-1"))


async def test_a_right_code_gives_its_slot_back(rig: Rig) -> None:
    started = await rig.start.execute()
    for _ in range(12):
        await _preview(rig).execute(LEAD, started.code_display)
