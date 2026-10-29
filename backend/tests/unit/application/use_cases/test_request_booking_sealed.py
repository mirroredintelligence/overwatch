"""RequestBooking queues its request the way the I10 senders read it (U17-1, DEC-305, DEC-116).

The request carries `sealed_content` and nothing else of the message; the Communication keeps the
link as the placeholder; no link token, no full link and no postcode is stored or queued in clear.
The tenant's referral wording comes from the tenant, through `wording_for`, never from the use case.

The use case runs here on a small recording unit of work (there is no in-memory unit of work,
DEC-004: the stored effects on real Neo4j are in
tests/integration/application/test_request_booking.py).
Sample values only: the case holds its district, never a full postcode (DEC-067).
"""

import json
import random
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, Self

import pytest

from diucs.adapters.outbound.content_seal.aes_gcm import AesGcmContentSealer
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_ids import SequentialIds
from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.application.actor import Actor
from diucs.application.ports.outbound.tokens import LINK_TOKEN_SECRET
from diucs.application.tenancy import ScopeId, bind_scope
from diucs.application.use_cases.request_booking import (
    RequestBooking,
    RequestBookingCommand,
)
from diucs.domain.codes import AgeBand, Channel, NeedCategory, ReferrerType, Role, Urgency
from diucs.domain.errors import ValidationFailed
from diucs.domain.model.case import Case
from diucs.domain.model.tenant import TenantWording

NOW = datetime(2026, 10, 29, 14, 16, tzinfo=UTC)
TENANT = "tenant-unit-a"
SERVICE_ID = "ucr-west"
ROLE_ID = "role-1"
TOKEN = "TOKENtokenTOKEN0123456789abcdef"
LINK_HOST = "https://unit.diucs.example"
FULL_LINK = f"{LINK_HOST}/l/{TOKEN}"
DISTRICT = "DT4"
WORDING = TenantWording(
    system_name="Unit test capacity",
    referral_system_name="SystmOne",
    coordination_team_name="The SPOA shift lead",
)
SECRETS = FixedSecretStore({LINK_TOKEN_SECRET: b"link-token-test-secret-0123456789abcdef"})
SEALER = AesGcmContentSealer(SECRETS)
ADVISOR = Actor(
    role=Role.ADVISOR,
    practitioner_id="advisor-1",
    device_id=None,
    channel="web",
    service_ids=frozenset(),
)
CASE = Case(
    id="case-1",
    reference="1001",
    referrer_type=ReferrerType.GP,
    age_band=AgeBand.A80_PLUS,
    postcode=DISTRICT,
    needs=(NeedCategory.FALL_NO_INJURY, NeedCategory.FRAILTY),
    urgency=Urgency.WITHIN_2_HRS,
    scores=(),
    opened_at=NOW,
)


class _Collect:
    """A repository that keeps what it is given."""

    def __init__(self) -> None:
        self.items: list[Any] = []

    async def add(self, item: Any) -> None:
        self.items.append(item)

    async def append(self, item: Any) -> None:
        self.items.append(item)

    async def put(self, key: str, value: Any) -> None:
        self.items.append((key, value))

    async def save(self, item: Any) -> None:
        self.items.append(item)


class _Bookings(_Collect):
    async def open_for_service(self, service_id: str) -> list[Any]:
        return []

    async def get_by_reference(self, reference: str) -> None:
        return None


class _Idempotency(_Collect):
    async def get(self, key: str) -> None:
        return None


@dataclass
class _Unit:
    channel: Channel
    committed: bool = False
    stores: dict[str, _Collect] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("communications", "outbox", "audit", "scheduled_work", "link_tokens"):
            self.stores[name] = _Collect()
        self.stores["bookings"] = _Bookings()
        self.stores["idempotency"] = _Idempotency()
        role = SimpleNamespace(id=ROLE_ID, channel=self.channel, practitioner_id="prac-1")
        reporter = SimpleNamespace(phone_hash="p" * 64)
        self.cases = SimpleNamespace(get=self._async(CASE))
        self.services = SimpleNamespace(
            get=self._async(SimpleNamespace(id=SERVICE_ID, name="UCR West", active=True))
        )
        self.people = SimpleNamespace(
            reporter_roles_for_service=self._async([role]),
            get_practitioner=self._async(reporter),
        )

    @staticmethod
    def _async(value: Any) -> Any:
        async def get(*args: Any, **kwargs: Any) -> Any:
            return value

        return get

    def __getattr__(self, name: str) -> Any:
        try:
            return self.__dict__["stores"][name]
        except KeyError:
            raise AttributeError(name) from None

    @property
    def unit_scope(self) -> ScopeId:
        return ScopeId.tenant(TENANT)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def commit(self) -> None:
        self.committed = True


class _Tokens:
    def __init__(self) -> None:
        self.issued = 0

    async def issue(self, *args: Any, **kwargs: Any) -> str:
        self.issued += 1
        return TOKEN


class _Board:
    async def execute(self, query: object) -> Any:
        entry = SimpleNamespace(
            service_id=SERVICE_ID,
            reported_at=NOW.replace(hour=13),
            status=SimpleNamespace(value="accepting"),
            effective_available=4,
            pending=False,
        )
        return SimpleNamespace(entries=[entry])


async def _wording(scope: ScopeId) -> TenantWording | None:
    return WORDING


async def _no_wording(scope: ScopeId) -> TenantWording | None:
    return None


def _use_case(unit: _Unit, tokens: _Tokens, wording: Any = _wording) -> RequestBooking:
    clock = FixedClock(NOW)
    return RequestBooking(
        lambda: unit,  # type: ignore[arg-type, return-value]
        unit.stores["idempotency"],  # type: ignore[arg-type]
        lambda repo: tokens,  # type: ignore[arg-type, return-value]
        clock,
        SequentialIds("bk"),
        random.Random(7),
        _Board(),  # type: ignore[arg-type]
        SEALER,
        wording,
        link_base_url_for=lambda scope: LINK_HOST,
    )


async def _request(channel: Channel, wording: Any = _wording) -> tuple[_Unit, _Tokens]:
    unit = _Unit(channel)
    tokens = _Tokens()
    command = RequestBookingCommand(
        idempotency_key="req-1", actor=ADVISOR, case_id=CASE.id, service_id=SERVICE_ID
    )
    with bind_scope(ScopeId.tenant(TENANT)):
        await _use_case(unit, tokens, wording).execute(command)
    return unit, tokens


def _send_message(unit: _Unit) -> Any:
    sent = [m for m in unit.stores["outbox"].items if m.event_type == "SendMessage"]
    assert len(sent) == 1
    return sent[0]


def _opened(unit: _Unit) -> dict[str, Any]:
    message = _send_message(unit)
    text = SEALER.unseal(
        message.payload["sealed_content"],
        message_id=message.id,
        tenant_id=TENANT,
        recipient_role_id=ROLE_ID,
    )
    content: dict[str, Any] = json.loads(text)
    return content


@pytest.mark.parametrize("channel", [Channel.TEXT, Channel.EMAIL, Channel.PUSH])
async def test_the_send_message_carries_sealed_content_and_no_clear_text(channel: Channel) -> None:
    unit, _ = await _request(channel)

    payload = _send_message(unit).payload

    assert set(payload) == {
        "communication_id",
        "message_id",
        "channel",
        "recipient_role_id",
        "sealed_content",
    }


async def test_the_sealed_content_opens_for_its_own_message_tenant_and_role_only() -> None:
    unit, _ = await _request(Channel.TEXT)
    message = _send_message(unit)

    with pytest.raises(ValidationFailed):
        SEALER.unseal(
            message.payload["sealed_content"],
            message_id=message.id,
            tenant_id="tenant-unit-b",
            recipient_role_id=ROLE_ID,
        )
    assert _opened(unit)["text"]


async def test_the_text_request_holds_the_link_and_the_tenants_referral_wording() -> None:
    unit, tokens = await _request(Channel.TEXT)

    text = _opened(unit)["text"]

    assert FULL_LINK in text
    assert "SystmOne" in text
    assert "UCR West" in text
    assert tokens.issued == 1


async def test_the_email_request_holds_the_subject_the_html_and_the_wording() -> None:
    unit, _ = await _request(Channel.EMAIL)

    content = _opened(unit)

    assert content["subject"]
    assert content["html"]
    assert "SystmOne" in content["html"]
    assert FULL_LINK in content["text"]


async def test_the_push_request_needs_no_wording_and_no_link() -> None:
    unit, tokens = await _request(Channel.PUSH, _no_wording)

    assert FULL_LINK not in _opened(unit)["text"]
    assert tokens.issued == 0
    assert unit.committed


async def test_the_communication_stores_the_placeholder_not_the_link() -> None:
    unit, _ = await _request(Channel.TEXT)

    stored = unit.stores["communications"].items

    assert len(stored) == 1
    assert "[link]" in stored[0].payload_text
    assert TOKEN not in stored[0].payload_text
    assert LINK_HOST not in stored[0].payload_text


@pytest.mark.parametrize("channel", [Channel.TEXT, Channel.EMAIL, Channel.PUSH])
async def test_no_token_full_link_or_postcode_is_stored_or_queued_in_clear(
    channel: Channel,
) -> None:
    unit, _ = await _request(channel)

    everything = repr([store.items for store in unit.stores.values()])

    assert TOKEN not in everything
    assert FULL_LINK not in everything
    assert DISTRICT not in everything
    assert "8XX" not in everything


async def test_the_opened_content_holds_no_postcode_or_district() -> None:
    unit, _ = await _request(Channel.EMAIL)

    assert DISTRICT not in repr(_opened(unit))


async def test_a_tenant_with_no_wording_is_refused_before_anything_is_written() -> None:
    unit = _Unit(Channel.TEXT)
    tokens = _Tokens()
    command = RequestBookingCommand(
        idempotency_key="req-2", actor=ADVISOR, case_id=CASE.id, service_id=SERVICE_ID
    )

    with bind_scope(ScopeId.tenant(TENANT)), pytest.raises(ValidationFailed) as refused:
        await _use_case(unit, tokens, _no_wording).execute(command)

    assert refused.value.field == "referral_system_name"
    assert not unit.committed
    assert tokens.issued == 0


async def test_the_wording_is_asked_of_the_bound_tenant() -> None:
    asked: list[ScopeId] = []

    async def wording(scope: ScopeId) -> TenantWording | None:
        asked.append(scope)
        return WORDING

    await _request(Channel.TEXT, wording)

    assert asked == [ScopeId.tenant(TENANT)]
