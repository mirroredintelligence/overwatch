"""Stopping a number, the shared sending line and the test text (DEC-1319).

Three operator use cases over the same recording fakes as `test_tenant_admin.py`: no Neo4j, no
network. What a real graph holds is `tests/integration/application/test_tenant_numbers.py`. The
destination of a test text is personal data: several tests below look for it in everything the use
case wrote, logged or raised, and must never find it. Every number is invented.
"""

import logging
from dataclasses import replace
from typing import Any

import pytest

from overwatch.adapters.testing.recording_senders import RecordingSmsSender
from overwatch.application.ports.outbound.messaging import (
    SendFailedError,
    SendReceipt,
    TransientSendError,
)
from overwatch.application.ports.outbound.sender_resolver import ChannelUnavailable
from overwatch.application.ports.outbound.tenant_registry import TenantNumberRecord
from overwatch.application.use_cases.tenant_admin import (
    NOT_SET_UP,
    TEST_TEXT,
    RecordNumberCommand,
    RecordTenantNumber,
    RetireNumberCommand,
    RetireTenantNumber,
    SendTestText,
    SendTestTextCommand,
    TextCheckFailed,
    UseSharedLine,
    UseSharedLineCommand,
)
from overwatch.domain.codes import Role
from overwatch.domain.errors import Conflict, NotAllowed, NotFound, ValidationFailed
from overwatch.domain.model.tenant import NumberStatus, TenantStatus
from overwatch.domain.model.tenant_records import ChannelKind
from overwatch.domain.rules.tenant_lifecycle import NUMBER_QUARANTINE
from tests.support.provisioning_fakes import (
    NOW,
    OTHER,
    TENANT,
    FakePlatform,
    FakeWorld,
    FixedNow,
    operator,
    provisioning_tenant,
)
from tests.support.tenancy import as_tenant

SID = "AC" + "1" * 32
NUMBER = "+447700900123"
SECOND = "+447700900124"
MOBILE = "07700 900456"
MOBILE_DIGITS = "07700900456"
MOBILE_TAIL = "900456"


def _record(platform: FakePlatform, world: FakeWorld) -> RecordTenantNumber:
    return RecordTenantNumber(platform, platform, world.factory(), FixedNow())  # type: ignore[arg-type]


def _retire(platform: FakePlatform, world: FakeWorld) -> RetireTenantNumber:
    return RetireTenantNumber(platform, platform, world.factory(), FixedNow())  # type: ignore[arg-type]


async def _with_number(platform: FakePlatform, world: FakeWorld, e164: str = NUMBER) -> None:
    with as_tenant(TENANT):
        await _record(platform, world).execute(RecordNumberCommand(operator(), e164, SID, "Sender"))


def _held(platform: FakePlatform, e164: str = NUMBER, tenant: str = TENANT) -> TenantNumberRecord:
    return platform.numbers_by_tenant[tenant][e164]


# ----------------------------------------------------------------------- stop using a number


async def test_a_number_that_is_stopped_is_retired_and_stays_held_by_the_tenant() -> None:
    platform, world = FakePlatform(provisioning_tenant()), FakeWorld()
    await _with_number(platform, world)
    world.audit.clear()

    with as_tenant(TENANT):
        changed = await _retire(platform, world).execute(RetireNumberCommand(operator(), NUMBER))

    assert changed is True
    held = _held(platform)
    assert held.status is NumberStatus.RETIRED
    assert held.quarantine_until == NOW + NUMBER_QUARANTINE
    # It is still the tenant's: nothing deleted, so no other tenant can be given it.
    assert list(platform.numbers_by_tenant[TENANT]) == [NUMBER]
    [channel] = world.config.channel_list
    assert channel.kind is ChannelKind.SMS and channel.status is NumberStatus.RETIRED
    assert world.audited() == ["RetireTenantNumber"]
    assert NUMBER not in repr(world.audit[0].snapshot)


async def test_stopping_a_number_twice_changes_nothing_the_second_time() -> None:
    platform, world = FakePlatform(provisioning_tenant()), FakeWorld()
    await _with_number(platform, world)
    with as_tenant(TENANT):
        assert await _retire(platform, world).execute(RetireNumberCommand(operator(), NUMBER))
        before = (_held(platform), list(world.config.channel_list), len(world.audit))
        assert not await _retire(platform, world).execute(RetireNumberCommand(operator(), NUMBER))
    assert (_held(platform), list(world.config.channel_list), len(world.audit)) == before


async def test_a_retired_number_stays_retired_with_its_original_quarantine() -> None:
    platform, world = FakePlatform(provisioning_tenant()), FakeWorld()
    await _with_number(platform, world)
    with as_tenant(TENANT):
        await _retire(platform, world).execute(RetireNumberCommand(operator(), NUMBER))
        first = _held(platform).quarantine_until
        use_case = RetireTenantNumber(
            platform, platform, world.factory(), FixedNow(NOW.replace(day=29))
        )  # type: ignore[arg-type]
        await use_case.execute(RetireNumberCommand(operator(), NUMBER))
    assert _held(platform).quarantine_until == first


async def test_only_the_number_named_is_stopped() -> None:
    platform, world = FakePlatform(provisioning_tenant()), FakeWorld()
    await _with_number(platform, world)
    await _with_number(platform, world, SECOND)
    with as_tenant(TENANT):
        await _retire(platform, world).execute(RetireNumberCommand(operator(), NUMBER))
    assert _held(platform, NUMBER).status is NumberStatus.RETIRED
    assert _held(platform, SECOND).status is NumberStatus.ACTIVE
    channels = {c.id: c.status for c in world.config.channel_list}
    assert channels == {
        "sms-447700900123": NumberStatus.RETIRED,
        "sms-447700900124": NumberStatus.ACTIVE,
    }


@pytest.mark.parametrize("e164", [SECOND, "+447700900999", "07700900123", "", "not a number"])
async def test_a_number_that_is_not_the_tenants_is_not_found_like_an_unknown_one(
    e164: str,
) -> None:
    platform, world = FakePlatform(provisioning_tenant(), provisioning_tenant(OTHER)), FakeWorld()
    platform.numbers_by_tenant[OTHER] = {
        SECOND: TenantNumberRecord(SECOND, SID, f"twilio/{OTHER}/auth-token")
    }
    await _with_number(platform, world)

    with as_tenant(TENANT), pytest.raises(NotFound) as refused:
        await _retire(platform, world).execute(RetireNumberCommand(operator(), e164))

    assert e164 not in str(refused.value) or e164 == ""
    # Another tenant's number is untouched.
    assert _held(platform, SECOND, OTHER).status is NumberStatus.ACTIVE
    assert _held(platform).status is NumberStatus.ACTIVE


async def test_the_refusal_for_another_tenants_number_is_the_same_as_for_an_unknown_one() -> None:
    platform, world = FakePlatform(provisioning_tenant(), provisioning_tenant(OTHER)), FakeWorld()
    platform.numbers_by_tenant[OTHER] = {
        SECOND: TenantNumberRecord(SECOND, SID, f"twilio/{OTHER}/auth-token")
    }
    messages = []
    for e164 in (SECOND, "+447700900999"):
        with as_tenant(TENANT), pytest.raises(NotFound) as refused:
            await _retire(platform, world).execute(RetireNumberCommand(operator(), e164))
        messages.append(str(refused.value))
    assert messages[0] == messages[1]


@pytest.mark.parametrize("role", [r for r in Role if r is not Role.PLATFORM_OPERATOR])
async def test_only_the_platform_operator_stops_a_number(role: Role) -> None:
    platform, world = FakePlatform(provisioning_tenant()), FakeWorld()
    await _with_number(platform, world)
    with as_tenant(TENANT), pytest.raises(NotAllowed):
        await _retire(platform, world).execute(RetireNumberCommand(operator(role=role), NUMBER))
    assert _held(platform).status is NumberStatus.ACTIVE


async def test_an_operator_of_another_tenant_cannot_stop_this_tenants_number() -> None:
    platform, world = FakePlatform(provisioning_tenant()), FakeWorld()
    await _with_number(platform, world)
    with as_tenant(TENANT), pytest.raises(Exception) as refused:
        await _retire(platform, world).execute(RetireNumberCommand(operator(tenant=OTHER), NUMBER))
    assert not isinstance(refused.value, AssertionError)
    assert _held(platform).status is NumberStatus.ACTIVE


async def test_a_tenant_that_has_left_cannot_have_a_number_stopped() -> None:
    gone = provisioning_tenant(
        status=TenantStatus.OFFBOARDING, activated_at=NOW, offboarding_started_at=NOW
    )
    platform, world = FakePlatform(gone), FakeWorld()
    platform.numbers_by_tenant[TENANT] = {
        NUMBER: TenantNumberRecord(NUMBER, SID, f"twilio/{TENANT}/auth-token")
    }
    with as_tenant(TENANT), pytest.raises(NotAllowed):
        await _retire(platform, world).execute(RetireNumberCommand(operator(), NUMBER))


async def test_a_stopped_number_no_longer_counts_for_activation() -> None:
    from overwatch.application.provisioning import count_tested_numbers

    platform, world = FakePlatform(provisioning_tenant()), FakeWorld()
    await _with_number(platform, world)
    platform.numbers_by_tenant[TENANT][NUMBER] = replace(_held(platform), tested_at=NOW)
    assert count_tested_numbers(tuple(platform.numbers_by_tenant[TENANT].values())) == 1
    with as_tenant(TENANT):
        await _retire(platform, world).execute(RetireNumberCommand(operator(), NUMBER))
    assert count_tested_numbers(tuple(platform.numbers_by_tenant[TENANT].values())) == 0


# ------------------------------------------------------------------------- the shared line


def _shared(platform: FakePlatform, world: FakeWorld, *, available: bool = True) -> UseSharedLine:
    return UseSharedLine(platform, world.factory(), FixedNow(), available=available)  # type: ignore[arg-type]


async def test_the_shared_line_is_recorded_as_a_shared_sms_channel_and_no_registry_number() -> None:
    platform, world = FakePlatform(provisioning_tenant()), FakeWorld()

    with as_tenant(TENANT):
        channel_id = await _shared(platform, world).execute(UseSharedLineCommand(operator()))

    [channel] = world.config.channel_list
    assert channel.id == channel_id == "sms-shared"
    assert channel.shared is True and channel.kind is ChannelKind.SMS
    assert channel.status is NumberStatus.ACTIVE
    assert channel.account_sid is None and channel.secret_ref is None
    # The registry is never written: the shared number is not this tenant's number.
    assert platform.calls == [] and platform.numbers_by_tenant.get(TENANT, {}) == {}
    assert world.audited() == ["UseSharedLine"]


async def test_choosing_the_shared_line_again_keeps_its_test_and_changes_nothing_else() -> None:
    platform, world = FakePlatform(provisioning_tenant()), FakeWorld()
    with as_tenant(TENANT):
        await _shared(platform, world).execute(UseSharedLineCommand(operator()))
        world.config.channel_list = [
            replace(world.config.channel_list[0], tested_at=NOW, test_message_id="SM1")
        ]
        await _shared(platform, world).execute(UseSharedLineCommand(operator()))
    [channel] = world.config.channel_list
    assert channel.tested_at == NOW and channel.test_message_id == "SM1"


async def test_the_shared_line_is_refused_when_the_platform_has_none() -> None:
    platform, world = FakePlatform(provisioning_tenant()), FakeWorld()
    with as_tenant(TENANT), pytest.raises(Conflict):
        await _shared(platform, world, available=False).execute(UseSharedLineCommand(operator()))
    assert world.config.channel_list == [] and world.opened == 0


@pytest.mark.parametrize("role", [r for r in Role if r is not Role.PLATFORM_OPERATOR])
async def test_only_the_platform_operator_chooses_the_shared_line(role: Role) -> None:
    platform, world = FakePlatform(provisioning_tenant()), FakeWorld()
    with as_tenant(TENANT), pytest.raises(NotAllowed):
        await _shared(platform, world).execute(UseSharedLineCommand(operator(role=role)))
    assert world.config.channel_list == []


# ------------------------------------------------------------------------- the test text


class _Resolver:
    """What the use case asks for: the sender of one line. Records the line it was asked for."""

    def __init__(self, sender: Any = None, error: Exception | None = None) -> None:
        self.sender = sender if sender is not None else RecordingSmsSender("line")
        self.error = error
        self.asked: list[TenantNumberRecord | None] = []

    async def provisioning_sms_for(self, number: TenantNumberRecord | None) -> Any:
        self.asked.append(number)
        if self.error is not None:
            raise self.error
        return self.sender


class _Ids:
    def new_id(self) -> str:
        return "id-1"


def _send(platform: FakePlatform, world: FakeWorld, resolver: _Resolver) -> SendTestText:
    return SendTestText(platform, platform, world.factory(), FixedNow(), _Ids(), resolver)  # type: ignore[arg-type]


def _command(**fields: Any) -> SendTestTextCommand:
    return SendTestTextCommand(**{"actor": operator(), "to": MOBILE, "e164": NUMBER, **fields})


async def test_a_test_text_goes_from_the_own_line_with_fixed_wording_and_marks_it_tested() -> None:
    platform, world = FakePlatform(provisioning_tenant()), FakeWorld()
    await _with_number(platform, world)
    resolver = _Resolver()

    with as_tenant(TENANT):
        await _send(platform, world, resolver).execute(_command())

    [asked] = resolver.asked
    assert asked is not None and asked.e164 == NUMBER
    [sent] = resolver.sender.sent
    assert sent.to == MOBILE
    assert sent.text == "This is a test from Overwatch for New Organisation. No action is needed."
    assert sent.text == TEST_TEXT.format(organisation="New Organisation")
    held = _held(platform)
    assert held.tested_at == NOW and held.test_message_id == "sms-1"
    assert world.audited()[-1] == "SendTestText"


async def test_the_destination_is_never_stored_logged_audited_or_in_the_message_id(
    caplog: pytest.LogCaptureFixture,
) -> None:
    platform, world = FakePlatform(provisioning_tenant()), FakeWorld()
    await _with_number(platform, world)
    resolver = _Resolver()

    with caplog.at_level(logging.DEBUG), as_tenant(TENANT):
        await _send(platform, world, resolver).execute(_command())

    everything = repr(
        (platform.numbers_by_tenant, world.config.channel_list, world.audit, platform.calls)
    )
    for needle in (MOBILE, MOBILE_DIGITS, MOBILE_TAIL):
        assert needle not in everything
        assert needle not in caplog.text
    assert resolver.sender.sent[0].message_id == "test-id-1"


async def test_a_test_text_from_a_number_not_held_is_not_found_and_sends_nothing() -> None:
    platform, world = FakePlatform(provisioning_tenant(), provisioning_tenant(OTHER)), FakeWorld()
    platform.numbers_by_tenant[OTHER] = {
        SECOND: TenantNumberRecord(SECOND, SID, f"twilio/{OTHER}/auth-token")
    }
    resolver = _Resolver()
    with as_tenant(TENANT), pytest.raises(NotFound) as refused:
        await _send(platform, world, resolver).execute(_command(e164=SECOND))
    assert resolver.asked == [] and resolver.sender.sent == []
    assert MOBILE not in str(refused.value) and SECOND not in str(refused.value)


async def test_a_retired_line_cannot_send_and_says_the_account_is_not_set_up() -> None:
    platform, world = FakePlatform(provisioning_tenant()), FakeWorld()
    await _with_number(platform, world)
    with as_tenant(TENANT):
        await _retire(platform, world).execute(RetireNumberCommand(operator(), NUMBER))
    resolver = _Resolver()

    with as_tenant(TENANT), pytest.raises(TextCheckFailed) as refused:
        await _send(platform, world, resolver).execute(_command())

    assert refused.value.reason == "not-set-up" and str(refused.value) == NOT_SET_UP
    assert resolver.sender.sent == [] and _held(platform).tested_at is None


async def test_an_account_that_cannot_send_says_so_in_fixed_words_and_leaks_nothing() -> None:
    platform, world = FakePlatform(provisioning_tenant()), FakeWorld()
    await _with_number(platform, world)
    resolver = _Resolver(error=ChannelUnavailable(f"no text channel for tenant {TENANT}"))

    with as_tenant(TENANT), pytest.raises(TextCheckFailed) as refused:
        await _send(platform, world, resolver).execute(_command())

    assert refused.value.reason == "not-set-up"
    text = str(refused.value)
    assert text == NOT_SET_UP and "organisation" in text.lower()
    for leak in (TENANT, NUMBER, MOBILE, SID, "twilio/"):
        assert leak not in text
    assert _held(platform).tested_at is None


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (TransientSendError("the provider could not be reached"), "try-again"),
        (SendFailedError("the provider answered 401 with code 20003"), "not-set-up"),
    ],
)
async def test_a_provider_failure_is_a_fixed_reason_and_marks_nothing(
    error: Exception, reason: str
) -> None:
    class _Failing:
        async def send(self, to: str, text: str, message_id: str) -> SendReceipt:
            raise error

    platform, world = FakePlatform(provisioning_tenant()), FakeWorld()
    await _with_number(platform, world)
    with as_tenant(TENANT), pytest.raises(TextCheckFailed) as refused:
        await _send(platform, world, _Resolver(_Failing())).execute(_command())
    assert refused.value.reason == reason
    for leak in (MOBILE, MOBILE_DIGITS, "20003", "401"):
        assert leak not in str(refused.value)
    assert _held(platform).tested_at is None


async def test_a_refusal_by_the_provider_marks_nothing_and_does_not_echo_the_number() -> None:
    sender = RecordingSmsSender("line")
    sender.fail_next()
    platform, world = FakePlatform(provisioning_tenant()), FakeWorld()
    await _with_number(platform, world)
    with as_tenant(TENANT), pytest.raises(TextCheckFailed) as refused:
        await _send(platform, world, _Resolver(sender)).execute(_command())
    assert refused.value.reason == "refused"
    assert MOBILE not in str(refused.value)
    assert _held(platform).tested_at is None


@pytest.mark.parametrize(
    "to", ["", "not a number", "01632 960001", "+1 202 555 0100", "0770090045"]
)
async def test_a_destination_that_is_not_a_uk_mobile_is_refused_before_anything_is_sent(
    to: str,
) -> None:
    class _Strict:
        sent = False

        async def send(self, text_to: str, text: str, message_id: str) -> SendReceipt:
            raise ValueError("not a UK mobile number")

    platform, world = FakePlatform(provisioning_tenant()), FakeWorld()
    await _with_number(platform, world)
    with as_tenant(TENANT), pytest.raises(ValidationFailed) as refused:
        await _send(platform, world, _Resolver(_Strict())).execute(_command(to=to))
    assert to.strip() not in str(refused.value) or not to.strip()
    assert _held(platform).tested_at is None


async def test_the_shared_line_test_marks_the_shared_channel_tested_and_never_the_registry() -> (
    None
):
    platform, world = FakePlatform(provisioning_tenant()), FakeWorld()
    with as_tenant(TENANT):
        await _shared(platform, world).execute(UseSharedLineCommand(operator()))
        platform.calls.clear()
        resolver = _Resolver()
        await _send(platform, world, resolver).execute(_command(e164=None))

    assert resolver.asked == [None]
    [channel] = world.config.channel_list
    assert channel.tested_at == NOW and channel.test_message_id == "sms-1"
    assert platform.calls == [] and platform.numbers_by_tenant.get(TENANT, {}) == {}
    assert MOBILE not in repr((world.config.channel_list, world.audit))


async def test_the_shared_line_cannot_be_tested_until_the_tenant_uses_it() -> None:
    platform, world = FakePlatform(provisioning_tenant()), FakeWorld()
    resolver = _Resolver()
    with as_tenant(TENANT), pytest.raises(TextCheckFailed) as refused:
        await _send(platform, world, resolver).execute(_command(e164=None))
    assert refused.value.reason == "not-set-up" and resolver.sender.sent == []


async def test_a_shared_line_counts_for_activation_only_after_its_test_text() -> None:
    from overwatch.application.use_cases.tenant_config import configuration_facts

    platform, world = FakePlatform(provisioning_tenant()), FakeWorld()
    with as_tenant(TENANT):
        await _shared(platform, world).execute(UseSharedLineCommand(operator()))
        before = configuration_facts(None, (), tuple(world.config.channel_list), (), (), ())
        await _send(platform, world, _Resolver()).execute(_command(e164=None))
        after = configuration_facts(None, (), tuple(world.config.channel_list), (), (), ())
    assert before.shared_lines_tested == 0 and after.shared_lines_tested == 1


@pytest.mark.parametrize("role", [r for r in Role if r is not Role.PLATFORM_OPERATOR])
async def test_only_the_platform_operator_sends_a_test_text(role: Role) -> None:
    platform, world = FakePlatform(provisioning_tenant()), FakeWorld()
    await _with_number(platform, world)
    resolver = _Resolver()
    with as_tenant(TENANT), pytest.raises(NotAllowed):
        await _send(platform, world, resolver).execute(_command(actor=operator(role=role)))
    assert resolver.asked == []


async def test_a_tenant_that_has_left_sends_no_test_text() -> None:
    gone = provisioning_tenant(
        status=TenantStatus.OFFBOARDING, activated_at=NOW, offboarding_started_at=NOW
    )
    platform, world = FakePlatform(gone), FakeWorld()
    resolver = _Resolver()
    with as_tenant(TENANT), pytest.raises(NotAllowed):
        await _send(platform, world, resolver).execute(_command())
    assert resolver.asked == []
