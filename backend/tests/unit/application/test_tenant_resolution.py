"""Pre-session resolution (TEN-041, DEC-520): the inbound number directory and the token resolvers.

Nothing here reaches a store: the tenant directory and the unit of work are small stand-ins that
record what they were asked. The rules under test:

- an inbound number or a Twilio account resolves only to an ACTIVE tenant, and only when the number
  and the account have the shape they are looked up by; a suspended or damaged record answers as an
  unknown number (known issue TEN-007: the SMS edge must not tell them apart);
- a link, an invitation or a device token is found only inside the bound tenant, so another
  tenant's token, an unknown one, one of another purpose and one that cannot be a token are the one
  `EntryRefused`, with the same fixed message and nothing of the request in it;
- an open link is returned open, and an expired or used one is returned with its state by `link` and
  refused by `open_link`;
- no number, account, token or hash reaches a log line.
"""

import logging
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.application.ports.outbound.identity import DEVICE_TOKEN_SECRET
from diucs.application.ports.outbound.tenant_lines import InboundLine
from diucs.application.ports.outbound.tenants import (
    TenantLine,
    TenantRecordInvalid,
    secret_ref,
    twilio_token_ref,
)
from diucs.application.ports.outbound.tokens import LINK_TOKEN_SECRET
from diucs.application.tenancy import ScopeId, bind_tenant
from diucs.application.tenant_resolution import (
    ENTRY_REFUSED_MESSAGE,
    DirectoryInboundLines,
    EntryKind,
    EntryRefused,
    PreSessionResolver,
)
from diucs.domain.errors import Conflict, NotFound
from diucs.domain.model.device import BoardScope, Device, DeviceStatus, DeviceType
from diucs.domain.model.tenant import Tenant, TenantStatus
from diucs.domain.rules.tokens import LinkCheck, LinkTokenRecord, hash_token
from tests.support.pre_session import Devices, Links, Uow
from tests.support.tenant_samples import make_tenant

pytestmark = pytest.mark.asyncio(loop_scope="session")

NOW = datetime(2026, 10, 30, 10, 0, tzinfo=UTC)
NUMBER = "+447700900123"
ACCOUNT = "AC" + "a" * 32
LINK_SECRET = b"synthetic-link-secret-for-resolver-tests-0123456789"
DEVICE_SECRET = b"synthetic-device-secret-for-resolver-tests-012345"
TENANT_A_SCOPE = ScopeId.tenant("tenant-a")
TOKEN = "AbCdEfGhIjKlMnOpQrStUvW"  # 23 letters, the shape of a link token
OTHER_TOKEN = "WvUtSrQpOnMlKjIhGfEdCbA"
DEVICE_TOKEN = "ZyXwVuTsRqPoNmLkJiHgFeD"


# ----------------------------------------------------------------------- the inbound directory


def _line(tenant: Tenant, number: str = NUMBER, account: str = ACCOUNT) -> TenantLine:
    return TenantLine(
        tenant=tenant, number=number, account_sid=account, secret_ref=twilio_token_ref(tenant.id)
    )


class _Directory:
    """The two lookups of the directory the resolver uses; records what it was asked."""

    def __init__(self, line: TenantLine | Exception | None) -> None:
        self.line = line
        self.asked: list[tuple[str, ...]] = []

    async def by_inbound_number(self, to_number: str, account_sid: str) -> TenantLine | None:
        self.asked.append((to_number, account_sid))
        return self._answer()

    async def by_account_sid(self, account_sid: str) -> TenantLine | None:
        self.asked.append((account_sid,))
        return self._answer()

    def _answer(self) -> TenantLine | None:
        if isinstance(self.line, Exception):
            raise self.line
        return self.line


def _lines(line: TenantLine | Exception | None) -> tuple[DirectoryInboundLines, _Directory]:
    directory = _Directory(line)
    return DirectoryInboundLines(directory), directory  # type: ignore[arg-type]


async def test_an_active_tenants_number_resolves_to_its_tenant_and_its_token_reference() -> None:
    tenant = make_tenant(TenantStatus.ACTIVE, id="tenant-a")
    lines, _ = _lines(_line(tenant))

    found = await lines.for_number(NUMBER, ACCOUNT)

    assert found == InboundLine(tenant_id="tenant-a", token_secret=twilio_token_ref("tenant-a"))


async def test_an_active_tenants_account_resolves_for_a_delivery_receipt() -> None:
    tenant = make_tenant(TenantStatus.ACTIVE, id="tenant-a")
    lines, _ = _lines(_line(tenant))

    assert await lines.for_account(ACCOUNT) == InboundLine(
        tenant_id="tenant-a", token_secret=twilio_token_ref("tenant-a")
    )


async def test_a_number_nobody_owns_is_none() -> None:
    lines, _ = _lines(None)

    assert await lines.for_number(NUMBER, ACCOUNT) is None
    assert await lines.for_account(ACCOUNT) is None


@pytest.mark.parametrize(
    "status",
    [
        TenantStatus.PROVISIONING,
        TenantStatus.SUSPENDED,
        TenantStatus.OFFBOARDING,
        TenantStatus.OFFBOARDED,
        TenantStatus.PURGED,
    ],
)
async def test_a_tenant_that_is_not_active_answers_as_an_unknown_number(
    status: TenantStatus,
) -> None:
    lines, _ = _lines(_line(make_tenant(status, id="tenant-a")))

    assert await lines.for_number(NUMBER, ACCOUNT) is None
    assert await lines.for_account(ACCOUNT) is None


@pytest.mark.parametrize(
    ("number", "account"),
    [
        ("07700900123", ACCOUNT),  # not E.164
        ("+447700900123 ", ACCOUNT),
        (NUMBER, "ac" + "a" * 32),  # SIDs are upper-case AC and lower-case hex
        (NUMBER, "AC" + "a" * 31),
        ("", ""),
        (None, ACCOUNT),
        (NUMBER, None),
    ],
)
async def test_a_number_or_account_of_the_wrong_shape_is_not_looked_up(
    number: Any, account: Any
) -> None:
    lines, directory = _lines(_line(make_tenant(id="tenant-a")))

    assert await lines.for_number(number, account) is None
    assert directory.asked == []


async def test_an_account_of_the_wrong_shape_is_not_looked_up_for_a_receipt() -> None:
    lines, directory = _lines(_line(make_tenant(id="tenant-a")))

    assert await lines.for_account("not-an-account") is None
    assert directory.asked == []


async def test_a_damaged_registry_record_answers_as_an_unknown_number_and_logs_a_reason_only(
    caplog: pytest.LogCaptureFixture,
) -> None:
    lines, _ = _lines(TenantRecordInvalid("a tenant record in the registry is not valid"))

    with caplog.at_level(logging.DEBUG):
        assert await lines.for_number(NUMBER, ACCOUNT) is None
        assert await lines.for_account(ACCOUNT) is None

    assert "tenant-record" in caplog.text
    assert NUMBER not in caplog.text
    assert ACCOUNT not in caplog.text


async def test_a_failure_of_the_directory_other_than_a_damaged_record_is_raised() -> None:
    # A route with no tenant must not open because the directory was down.
    lines, _ = _lines(ConnectionError("down"))

    with pytest.raises(ConnectionError):
        await lines.for_number(NUMBER, ACCOUNT)
    with pytest.raises(ConnectionError):
        await lines.for_account(ACCOUNT)


async def test_a_line_that_names_another_tenants_token_is_refused() -> None:
    # Defence in depth: the directory checks this too, and the resolver does not trust it.
    other = TenantLine(
        tenant=make_tenant(id="tenant-a"),
        number=NUMBER,
        account_sid=ACCOUNT,
        secret_ref=secret_ref("twilio", "tenant-b", "auth-token"),
    )
    lines, _ = _lines(other)

    assert await lines.for_number(NUMBER, ACCOUNT) is None
    assert await lines.for_account(ACCOUNT) is None


async def test_a_directory_answer_that_is_not_a_line_is_refused() -> None:
    lines, _ = _lines(object())  # type: ignore[arg-type]

    assert await lines.for_number(NUMBER, ACCOUNT) is None


async def test_the_inbound_line_holds_no_number_and_no_account() -> None:
    lines, _ = _lines(_line(make_tenant(id="tenant-a")))

    found = await lines.for_number(NUMBER, ACCOUNT)

    assert found is not None
    assert NUMBER not in repr(found)
    assert ACCOUNT not in repr(found)


# ----------------------------------------------------------------------- the token resolvers


def _record(
    token: str = TOKEN,
    purpose: str = "capacity-reply",
    *,
    expires_in: timedelta = timedelta(minutes=30),
    used: bool = False,
) -> LinkTokenRecord:
    return LinkTokenRecord(
        token_hash=hash_token(token, LINK_SECRET),
        purpose=purpose,
        about_id="c-1",
        phone_hash="f" * 64,
        expires_at=NOW + expires_in,
        used_at=NOW - timedelta(minutes=1) if used else None,
    )


def _device(status: DeviceStatus = DeviceStatus.ACTIVE) -> Device:
    return Device(
        id="dev-1",
        status=status,
        name="Ward screen",
        location=None,
        device_type=DeviceType.WALL_DISPLAY,
        token_hash=hash_token(DEVICE_TOKEN, DEVICE_SECRET),
        board_scope=BoardScope.TENANT,
    )


def _resolver(
    records: list[LinkTokenRecord] | None = None,
    devices: dict[str, Device | Exception] | None = None,
    *,
    scope: ScopeId | None = TENANT_A_SCOPE,
) -> tuple[PreSessionResolver, Uow]:
    links = Links({r.token_hash: r for r in records or []})
    uow = Uow(links, Devices(devices or {}), scope)
    secrets = FixedSecretStore({LINK_TOKEN_SECRET: LINK_SECRET, DEVICE_TOKEN_SECRET: DEVICE_SECRET})
    resolver = PreSessionResolver(lambda: uow, FixedClock(NOW), secrets)  # type: ignore[arg-type,return-value]
    return resolver, uow


async def test_an_open_link_is_resolved_open() -> None:
    resolver, _ = _resolver([_record()])

    with bind_tenant("tenant-a"):
        found = await resolver.link(TOKEN, {"capacity-reply"})

    assert found.state is LinkCheck.OK
    assert found.record.purpose == "capacity-reply"


async def test_an_expired_link_is_resolved_with_its_state() -> None:
    resolver, _ = _resolver([_record(expires_in=timedelta(seconds=-1))])

    with bind_tenant("tenant-a"):
        found = await resolver.link(TOKEN, {"capacity-reply"})

    assert found.state is LinkCheck.EXPIRED


async def test_a_used_link_is_resolved_as_used_even_when_it_has_expired() -> None:
    resolver, _ = _resolver([_record(expires_in=timedelta(seconds=-1), used=True)])

    with bind_tenant("tenant-a"):
        found = await resolver.link(TOKEN, {"capacity-reply"})

    assert found.state is LinkCheck.USED


@pytest.mark.parametrize(
    "state",
    [
        _record(expires_in=timedelta(seconds=-1)),
        _record(used=True),
        _record(expires_in=timedelta(seconds=-1), used=True),
    ],
)
async def test_an_open_link_is_refused_unless_it_is_open(state: LinkTokenRecord) -> None:
    resolver, _ = _resolver([state])

    with bind_tenant("tenant-a"), pytest.raises(EntryRefused):
        await resolver.open_link(TOKEN, {"capacity-reply"})


async def test_an_open_link_is_returned_by_open_link() -> None:
    resolver, _ = _resolver([_record()])

    with bind_tenant("tenant-a"):
        found = await resolver.open_link(TOKEN, {"capacity-reply"})

    assert found.state is LinkCheck.OK


async def test_an_unknown_link_and_a_link_of_another_purpose_are_refused_alike() -> None:
    resolver, _ = _resolver([_record(purpose="pairing-code")])

    messages = set()
    with bind_tenant("tenant-a"):
        for token, purposes in (
            (OTHER_TOKEN, {"capacity-reply"}),  # nobody holds it
            (TOKEN, {"capacity-reply"}),  # held, but for another purpose
        ):
            with pytest.raises(EntryRefused) as caught:
                await resolver.link(token, purposes)
            messages.add(str(caught.value))

    assert messages == {ENTRY_REFUSED_MESSAGE}


@pytest.mark.parametrize("token", ["", "a b", "a/b", "x" * 5000, "tok\x00en", "é" * 23])
async def test_text_that_cannot_be_a_token_is_refused_without_a_lookup(token: str) -> None:
    resolver, uow = _resolver([_record()])

    with bind_tenant("tenant-a"), pytest.raises(EntryRefused):
        await resolver.link(token, {"capacity-reply"})

    assert uow.link_tokens.asked == []  # type: ignore[attr-defined]


async def test_a_token_that_is_not_text_is_refused() -> None:
    resolver, _ = _resolver([_record()])

    with bind_tenant("tenant-a"), pytest.raises(EntryRefused):
        await resolver.link(None, {"capacity-reply"})  # type: ignore[arg-type]


async def test_a_link_is_looked_up_by_its_keyed_hash_and_never_by_the_token() -> None:
    resolver, uow = _resolver([_record()])

    with bind_tenant("tenant-a"):
        await resolver.link(TOKEN, {"capacity-reply"})

    assert uow.link_tokens.asked == [hash_token(TOKEN, LINK_SECRET)]  # type: ignore[attr-defined]


async def test_an_invitation_is_a_link_of_the_invitation_purpose() -> None:
    resolver, _ = _resolver([_record(purpose="invite"), _record(OTHER_TOKEN, "capacity-reply")])

    with bind_tenant("tenant-a"):
        found = await resolver.invitation(TOKEN)
        with pytest.raises(EntryRefused):
            await resolver.invitation(OTHER_TOKEN)  # a capacity link is not an invitation

    assert found.record.purpose == "invite"


async def test_a_resolver_needs_a_bound_tenant_scope() -> None:
    # The unit of work binds the scope; a unit with no scope, or a network scope, resolves nothing.
    for scope in (None, ScopeId.network("net-region-1")):
        resolver, uow = _resolver([_record()], scope=scope)
        with bind_tenant("tenant-a"), pytest.raises(Exception) as caught:
            await resolver.link(TOKEN, {"capacity-reply"})
        assert not isinstance(caught.value, EntryRefused)
        assert uow.link_tokens.asked == []  # type: ignore[attr-defined]


async def test_a_resolver_reads_and_never_commits() -> None:
    resolver, uow = _resolver([_record()], {hash_token(DEVICE_TOKEN, DEVICE_SECRET): _device()})

    with bind_tenant("tenant-a"):
        await resolver.link(TOKEN, {"capacity-reply"})
        await resolver.device(DEVICE_TOKEN)

    assert uow.committed is False


async def test_an_active_device_is_resolved_by_its_keyed_hash() -> None:
    resolver, uow = _resolver(devices={hash_token(DEVICE_TOKEN, DEVICE_SECRET): _device()})

    with bind_tenant("tenant-a"):
        found = await resolver.device(DEVICE_TOKEN)

    assert found.id == "dev-1"
    assert uow.devices.asked == [hash_token(DEVICE_TOKEN, DEVICE_SECRET)]  # type: ignore[attr-defined]


async def test_an_unknown_device_token_is_refused_like_every_other_entry() -> None:
    resolver, _ = _resolver()

    with bind_tenant("tenant-a"), pytest.raises(EntryRefused) as caught:
        await resolver.device(DEVICE_TOKEN)

    assert str(caught.value) == ENTRY_REFUSED_MESSAGE


@pytest.mark.parametrize("status", [DeviceStatus.REVOKED, DeviceStatus.PAIRED_UNCLAIMED])
async def test_a_device_that_is_not_active_is_refused_even_if_the_store_returns_it(
    status: DeviceStatus,
) -> None:
    # The port promises active devices only; a store that breaks it must not open the exchange.
    device = replace(_device(DeviceStatus.REVOKED), status=status, token_hash=None)
    resolver, _ = _resolver(devices={hash_token(DEVICE_TOKEN, DEVICE_SECRET): device})

    with bind_tenant("tenant-a"), pytest.raises(EntryRefused):
        await resolver.device(DEVICE_TOKEN)


async def test_two_devices_for_one_token_are_refused() -> None:
    resolver, _ = _resolver(devices={hash_token(DEVICE_TOKEN, DEVICE_SECRET): Conflict("two")})

    with bind_tenant("tenant-a"), pytest.raises(EntryRefused):
        await resolver.device(DEVICE_TOKEN)


async def test_a_device_token_that_cannot_be_a_token_is_refused_without_a_lookup() -> None:
    resolver, uow = _resolver(devices={})

    with bind_tenant("tenant-a"), pytest.raises(EntryRefused):
        await resolver.device("not a token")

    assert uow.devices.asked == []  # type: ignore[attr-defined]


async def test_a_missing_secret_is_a_configuration_fault_and_not_a_refusal() -> None:
    uow = Uow(Links({}), Devices({}), ScopeId.tenant("tenant-a"))
    resolver = PreSessionResolver(lambda: uow, FixedClock(NOW), FixedSecretStore({}))  # type: ignore[arg-type,return-value]

    # A refusal here would read a broken deployment as "no such device": it is a 500 instead.
    with bind_tenant("tenant-a"):
        with pytest.raises(RuntimeError):
            await resolver.device(DEVICE_TOKEN)
        with pytest.raises(RuntimeError):
            await resolver.link(TOKEN, {"capacity-reply"})


def test_the_refusal_is_a_not_found_with_a_fixed_message_that_names_nothing() -> None:
    error = EntryRefused()

    assert isinstance(error, NotFound)
    assert str(error) == ENTRY_REFUSED_MESSAGE
    for kind in EntryKind:
        assert kind.value not in ENTRY_REFUSED_MESSAGE


def test_the_entry_kinds_are_the_five_that_precede_a_session() -> None:
    assert {kind.value for kind in EntryKind} == {
        "link",
        "invitation",
        "device",
        "pairing",
        "inbound-number",
    }
