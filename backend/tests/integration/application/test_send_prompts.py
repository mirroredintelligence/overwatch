"""Integration tests for SendPrompts and the scheduling helpers (U03), on the real Neo4j.

Seeds go through committed units of work; assertions read back through a fresh unit of work or
the harness helpers. Synthetic values only: no patient data, no real phone number.

Clock: Friday 23 October 2026. The prompt is due at 10:00 London (09:00 UTC, BST). UCR West opens
08:00 to 20:00 every day and reports every 2 hours.
"""

import dataclasses
import json
import re
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from neo4j import AsyncDriver, AsyncManagedTransaction

from diucs.adapters.outbound.graph_store.idempotency_store import DriverIdempotencyStore
from diucs.adapters.outbound.graph_store.link_token_repository import Neo4jLinkTokenRepository
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_ids import SequentialIds
from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.application.actor import Actor
from diucs.application.ports.outbound.outbox import MAX_ATTEMPTS, OutboxMessage
from diucs.application.ports.outbound.tokens import LinkTokenRepository, LinkTokenService
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.scheduling import cancel_work, schedule_work
from diucs.application.use_cases import send_prompts as send_prompts_module
from diucs.application.use_cases.send_prompts import (
    SKIP_INACTIVE,
    SKIP_NO_REPORTER,
    SKIP_NO_WINDOW,
    SKIP_OUT_OF_HOURS,
    SKIP_REPLY_WINDOW,
    SKIP_SUSPENDED,
    SendPromptCommand,
    SendPrompts,
    derive_key,
    unseal_content,
)
from diucs.application.work import CANCELLED, SCHEDULED, ScheduledWork, WorkKind
from diucs.domain.codes import (
    Cadence,
    Channel,
    Measure,
    PractitionerRoleCode,
    ReportSource,
    ReportType,
    Role,
    ServiceCategory,
)
from diucs.domain.errors import Conflict, DomainError, NotFound, ValidationFailed
from diucs.domain.model.capacity import CapacityReport
from diucs.domain.model.flags import SERVICE_FLAG_SUSPENDED, ServiceFlag
from diucs.domain.model.people import Practitioner, PractitionerRole
from diucs.domain.model.service import AvailableTime, ServiceProfile
from tests.support.neo4j import count_nodes, read_tx

Seed = Callable[..., Awaitable[None]]

pytestmark = pytest.mark.asyncio(loop_scope="session")

SECRET = b"link-token-test-secret-0123456789abcdef"
TENANT = "tenant-a"
LINK_BASE = "diucs.example"
DUE = datetime(2026, 10, 23, 9, 0, tzinfo=UTC)  # 10:00 BST
PHONE_HASH_1 = "ab" * 32
PHONE_HASH_2 = "cd" * 32
LONDON = ZoneInfo("Europe/London")

SYSTEM_ACTOR = Actor(
    role=Role.OWNER, practitioner_id=None, device_id=None, channel="worker", service_ids=frozenset()
)

UCR_WEST = ServiceProfile(
    id="ucr-west",
    name="UCR West",
    category=ServiceCategory.URGENT_COMMUNITY_RESPONSE,
    measure=Measure.REFERRALS_ACCEPTABLE,
    unit_label="referrals in the next 2 hrs",
    established_capacity=8,
    can_exceed_established=False,
    usual_range=(0, 8),
    cadence=Cadence.EVERY_2_HRS,
    available_times=(AvailableTime.every_day(time(8, 0), time(20, 0)),),
    channel=Channel.TEXT,
    limited_level_percent=80,
)

ALL_COUNTED_LABELS = (
    "Communication",
    "LinkToken",
    "ScheduledWork",
    "OutboxMessage",
    "AuditEvent",
)


def _london(hour: int, minute: int) -> datetime:
    """A Friday 23 October 2026 London (BST) wall time as a UTC instant."""
    return datetime(2026, 10, 23, hour, minute, tzinfo=UTC) - timedelta(hours=1)


def _practitioner(number: int, phone_hash: str | None) -> Practitioner:
    return Practitioner(
        id=f"prac-{number}", active=True, display_name=f"Reporter {number}", phone_hash=phone_hash
    )


def _role(number: int, **changes: Any) -> PractitionerRole:
    role = PractitionerRole(
        id=f"role-{number}",
        practitioner_id=f"prac-{number}",
        service_id="ucr-west",
        code=PractitionerRoleCode.DUTY_MANAGER,
        active=True,
        channel=Channel.TEXT,
        period_start=datetime(2026, 1, 1, tzinfo=UTC),
    )
    return dataclasses.replace(role, **changes)


async def _seed_people(
    factory: UnitOfWorkFactory,
    practitioners: tuple[Practitioner, ...],
    roles: tuple[PractitionerRole, ...],
) -> None:
    async with factory() as uow:
        for practitioner in practitioners:
            await uow.people.save_practitioner(practitioner)
        for role in roles:
            await uow.people.save_role(role)
        await uow.commit()


async def _seed_report(
    factory: UnitOfWorkFactory, effective_at: datetime = datetime(2026, 10, 23, 7, 15, tzinfo=UTC)
) -> None:
    """The latest figure: 3 referrals, at 08:15 BST on Friday unless the test gives another time."""
    async with factory() as uow:
        await uow.capacity.add(
            CapacityReport(
                id="report-1",
                service_id="ucr-west",
                value=3,
                measure=Measure.REFERRALS_ACCEPTABLE,
                effective_at=effective_at,
                source=ReportSource.TEXT,
                report_type=ReportType.NUMBER,
            )
        )
        await uow.commit()


async def _seed_one_reporter(factory: UnitOfWorkFactory, seed_service: Seed) -> None:
    await seed_service(UCR_WEST)
    await _seed_people(factory, (_practitioner(1, PHONE_HASH_1),), (_role(1),))


def _rig(
    factory: UnitOfWorkFactory,
    driver: AsyncDriver,
    now: datetime = DUE,
    link_base: str = LINK_BASE,
) -> tuple[SendPrompts, FixedClock]:
    clock = FixedClock(now)

    def tokens(repo: LinkTokenRepository) -> LinkTokenService:
        return LinkTokenService(repo, FixedSecretStore({"link-token": SECRET}), clock)

    use_case = SendPrompts(
        factory,
        clock,
        SequentialIds(),
        DriverIdempotencyStore(driver),
        tokens,
        link_base,
        FixedSecretStore({"link-token": SECRET}),
        TENANT,
    )
    return use_case, clock


def _command(due_at: datetime = DUE, service_id: str = "ucr-west") -> SendPromptCommand:
    return SendPromptCommand(
        idempotency_key=f"prompt:{service_id}:{due_at.isoformat()}",
        actor=SYSTEM_ACTOR,
        service_id=service_id,
        due_at=due_at,
    )


async def _outbox(factory: UnitOfWorkFactory) -> list[OutboxMessage]:
    async with factory() as uow:
        return await uow.outbox.pending(limit=1000)


async def _works(
    factory: UnitOfWorkFactory, about_id: str, kind: WorkKind | None = None
) -> list[ScheduledWork]:
    async with factory() as uow:
        return await uow.scheduled_work.for_about(about_id, kind)


async def _counts(driver: AsyncDriver) -> dict[str, int]:
    return {label: await count_nodes(driver, label) for label in ALL_COUNTED_LABELS}


async def _every_node_property(driver: AsyncDriver) -> list[dict[str, Any]]:
    async def work(tx: AsyncManagedTransaction) -> list[dict[str, Any]]:
        result = await tx.run("MATCH (n) RETURN properties(n) AS props")
        return await result.data()

    return [row["props"] for row in await read_tx(driver, work)]


async def _communication_rows(driver: AsyncDriver) -> list[dict[str, Any]]:
    async def work(tx: AsyncManagedTransaction) -> list[dict[str, Any]]:
        result = await tx.run(
            "MATCH (c:Communication) OPTIONAL MATCH (c)-[:TOPIC]->(t:Concept) "
            "OPTIONAL MATCH (c)-[:RECIPIENT]->(r:PractitionerRole) "
            "RETURN c.id AS id, c.payloadText AS text, c.deliveryStatus AS status, "
            "t.code AS messageId, r.id AS role ORDER BY c.id"
        )
        return await result.data()

    return await read_tx(driver, work)


def _sent(messages: list[OutboxMessage]) -> list[OutboxMessage]:
    return [m for m in messages if m.event_type == "SendMessage"]


def _opened(message: OutboxMessage, tenant: str = TENANT) -> dict[str, Any]:
    """The rendered content of one SendMessage, opened as the sender does: with the key derived from
    the link secret, and the message id, tenant and recipient role as associated data."""
    opened: dict[str, Any] = json.loads(
        unseal_content(
            message.payload["sealed_content"],
            derive_key(SECRET),
            message_id=message.id,
            tenant_id=tenant,
            recipient_role_id=message.payload["recipient_role_id"],
        )
    )
    return opened


TOKEN_IN_TEXT = re.compile(rf"{re.escape(LINK_BASE)}/(\S+) Or reply")


def _token_of(message: OutboxMessage) -> str:
    match = TOKEN_IN_TEXT.search(_opened(message)["text"])
    assert match is not None
    return match.group(1)


async def _resolve(driver: AsyncDriver, clock_at: datetime, token: str) -> Any:
    clock = FixedClock(clock_at)

    async def work(tx: AsyncManagedTransaction) -> Any:
        service = LinkTokenService(
            Neo4jLinkTokenRepository(tx), FixedSecretStore({"link-token": SECRET}), clock
        )
        return await service.resolve(token)

    return await read_tx(driver, work)


class _FailingAudit:
    """Stands in for the audit log: the append is the last write of a prompt, so every other write
    of the command has already been made when it fails."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    async def append(self, entry: Any) -> None:
        raise RuntimeError("audit write failed")

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


class _FailingAuditUnitOfWork:
    def __init__(self, inner: Any) -> None:
        self._inner = inner

    @property
    def audit(self) -> _FailingAudit:
        return _FailingAudit(self._inner.audit)

    async def __aenter__(self) -> _FailingAuditUnitOfWork:
        await self._inner.__aenter__()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self._inner.__aexit__(*exc)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


# --- C1 and C2 wording, the link, and what is stored (A, K) -------------------------------------


async def test_c1_text_carries_the_dated_figure_the_deadline_and_a_one_time_link(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await _seed_one_reporter(uow_factory, seed_service)
    await _seed_report(uow_factory)
    use_case, _ = _rig(uow_factory, neo4j_driver)

    result = await use_case.execute(_command())

    assert result.sent is True
    assert result.skipped_reason is None
    assert result.replayed is False
    [communication_id] = result.communication_ids
    [row] = await _communication_rows(neo4j_driver)
    assert row["id"] == communication_id
    assert row["messageId"] == "C1"
    assert row["status"] == "queued"
    assert row["role"] == "role-1"
    # K: the figure carries its full date and time, so a figure from another day cannot read as
    # the current one. The stored record holds the same words with the link replaced.
    assert row["text"] == (
        "DIUCS: UCR West. We have 3 referrals in the next 2 hrs (as of 23 Oct 08:15). "
        "Confirm or update: [link] Or reply Y, or a new number. By 10:30."
    )
    [message] = _sent(await _outbox(uow_factory))
    assert _opened(message)["text"].startswith(
        "DIUCS: UCR West. We have 3 referrals in the next 2 hrs (as of 23 Oct 08:15)."
    )
    token = _token_of(message)
    record = await _resolve(neo4j_driver, DUE, token)
    assert record is not None
    assert record.expires_at == _london(10, 30)
    assert record.used_at is None
    assert record.phone_hash == PHONE_HASH_1
    assert record.about_id == communication_id


async def test_a_figure_from_a_previous_day_shows_its_date(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    # K: a figure from Thursday 17:00 BST is shown with its day, not as a bare time.
    await _seed_one_reporter(uow_factory, seed_service)
    await _seed_report(uow_factory, effective_at=datetime(2026, 10, 22, 16, 0, tzinfo=UTC))
    use_case, _ = _rig(uow_factory, neo4j_driver)

    await use_case.execute(_command())

    [message] = _sent(await _outbox(uow_factory))
    text = _opened(message)["text"]
    assert "(as of 22 Oct 17:00)" in text
    assert "(as of 17:00)" not in text


async def test_with_no_earlier_report_the_first_prompt_c2_is_sent(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await _seed_one_reporter(uow_factory, seed_service)
    use_case, _ = _rig(uow_factory, neo4j_driver)

    result = await use_case.execute(_command())

    assert result.sent is True
    [row] = await _communication_rows(neo4j_driver)
    assert row["messageId"] == "C2"
    [message] = _sent(await _outbox(uow_factory))
    assert _opened(message)["text"] == (
        "DIUCS: UCR West. How many referrals can you take in the next 2 hrs? "
        "Send a number (0 = closed). By 10:30."
    )


async def test_c1_does_not_need_a_window_in_the_unit_label(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    # G: only C2 needs the window. A figure on record is sent as C1 whatever the label says.
    await seed_service(dataclasses.replace(UCR_WEST, unit_label="referrals"))
    await _seed_people(uow_factory, (_practitioner(1, PHONE_HASH_1),), (_role(1),))
    await _seed_report(uow_factory)
    use_case, _ = _rig(uow_factory, neo4j_driver)

    result = await use_case.execute(_command())

    assert result.sent is True
    [row] = await _communication_rows(neo4j_driver)
    assert row["messageId"] == "C1"


@pytest.mark.parametrize("label", ["referrals", "referrals in"])
async def test_a_first_prompt_with_no_readable_window_is_not_worded_and_is_recorded(
    label: str,
    uow_factory: UnitOfWorkFactory,
    neo4j_driver: AsyncDriver,
    seed_service: Seed,
) -> None:
    # G: C2 cannot be worded without the window, so nothing is invented. The refusal is recorded
    # in the audit entry, and the chain goes on (B).
    await seed_service(dataclasses.replace(UCR_WEST, unit_label=label))
    await _seed_people(uow_factory, (_practitioner(1, PHONE_HASH_1),), (_role(1),))
    use_case, _ = _rig(uow_factory, neo4j_driver)

    result = await use_case.execute(_command())

    assert result.sent is False
    assert result.communication_ids == ()
    assert result.skipped_reason == SKIP_NO_WINDOW
    assert await count_nodes(neo4j_driver, "Communication") == 0
    assert await count_nodes(neo4j_driver, "LinkToken") == 0
    [prompt_due] = await _works(uow_factory, "ucr-west", WorkKind.PROMPT_DUE)
    assert prompt_due.due_at == _london(12, 0)
    async with uow_factory() as uow:
        [record] = await uow.audit.records()
    assert record.entry.snapshot is not None
    assert record.entry.snapshot["skipped_reason"] == SKIP_NO_WINDOW


async def test_the_send_message_carries_sealed_content_and_no_phone(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await _seed_one_reporter(uow_factory, seed_service)
    await _seed_report(uow_factory)
    use_case, _ = _rig(uow_factory, neo4j_driver)

    result = await use_case.execute(_command())

    [message] = _sent(await _outbox(uow_factory))
    assert message.topic == "messages.outbound"
    assert message.payload["communication_id"] == result.communication_ids[0]
    assert message.payload["message_id"] == "C1"
    assert message.payload["channel"] == "text"
    assert message.payload["recipient_role_id"] == "role-1"
    assert "text" not in message.payload
    assert "sealed_content" in message.payload
    for outbox_message in await _outbox(uow_factory):
        rendered = repr(outbox_message.payload)
        assert PHONE_HASH_1 not in rendered
        assert not re.search(r"\b0?7\d{9}\b|\+44", rendered)


async def test_no_stored_node_and_no_outbox_payload_holds_the_token_text(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    # A: the token is never at rest. Only its hash is stored, and the outbox holds the content
    # sealed with the link secret. The sender opens it at send time.
    await _seed_one_reporter(uow_factory, seed_service)
    await _seed_report(uow_factory)
    use_case, _ = _rig(uow_factory, neo4j_driver)
    await use_case.execute(_command())

    [message] = _sent(await _outbox(uow_factory))
    token = _token_of(message)
    assert await _resolve(neo4j_driver, DUE, token) is not None
    for props in await _every_node_property(neo4j_driver):
        assert token not in repr(props)
    for outbox_message in await _outbox(uow_factory):
        assert token not in repr(outbox_message.payload)


async def test_a_dead_lettered_message_holds_no_token_text(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    # A: a message that fails until it is dead keeps its payload and an error text. Neither holds
    # a live link token (multi-tenancy rule: no message body at rest holds a token).
    await _seed_one_reporter(uow_factory, seed_service)
    await _seed_report(uow_factory)
    use_case, _ = _rig(uow_factory, neo4j_driver)
    await use_case.execute(_command())
    [message] = _sent(await _outbox(uow_factory))
    token = _token_of(message)

    async with uow_factory() as uow:
        for _ in range(MAX_ATTEMPTS):
            await uow.outbox.mark_failed(message.id, "send failed")
        await uow.commit()

    assert await _resolve(neo4j_driver, DUE, token) is not None
    for props in await _every_node_property(neo4j_driver):
        assert token not in repr(props)


async def test_sealed_content_opens_only_in_its_own_tenant(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    # A: the content is bound to its tenant. Opened as another tenant it is refused.
    await _seed_one_reporter(uow_factory, seed_service)
    await _seed_report(uow_factory)
    use_case, _ = _rig(uow_factory, neo4j_driver)
    await use_case.execute(_command())
    [message] = _sent(await _outbox(uow_factory))

    assert "text" in _opened(message)
    with pytest.raises(ValidationFailed):
        _opened(message, tenant="tenant-b")


async def test_the_use_case_writes_one_audit_entry(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await _seed_one_reporter(uow_factory, seed_service)
    use_case, _ = _rig(uow_factory, neo4j_driver)

    result = await use_case.execute(_command())

    async with uow_factory() as uow:
        records = await uow.audit.records()
        chain_ok = await uow.audit.verify_chain()
    assert chain_ok is True
    [record] = records
    assert record.entry.use_case == "SendPrompts"
    assert record.entry.actor == SYSTEM_ACTOR
    assert record.entry.entity_ids == (*result.communication_ids, "ucr-west")
    assert record.entry.snapshot == {
        "due_at": DUE.isoformat(),
        "prompts": 1,
        "skipped_reason": "none",
    }
    assert record.entry.at == DUE


async def test_a_no_reporter_prompt_audits_the_real_reason(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    # 4: the audit entry names the reason the prompt was not sent, as the result does.
    await seed_service(UCR_WEST)
    await _seed_people(uow_factory, (_practitioner(1, None),), (_role(1),))
    use_case, _ = _rig(uow_factory, neo4j_driver)

    result = await use_case.execute(_command())

    assert result.skipped_reason == SKIP_NO_REPORTER
    async with uow_factory() as uow:
        [record] = await uow.audit.records()
    assert record.entry.snapshot == {
        "due_at": DUE.isoformat(),
        "prompts": 0,
        "skipped_reason": SKIP_NO_REPORTER,
    }


# --- Skips re-arm the chain (B) ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("case", "due", "now", "profile", "flags", "reason", "next_prompt"),
    [
        (
            "suspended",
            DUE,
            DUE,
            UCR_WEST,
            "suspended",
            SKIP_SUSPENDED,
            _london(12, 0),
        ),
        (
            "inactive",
            DUE,
            DUE,
            dataclasses.replace(UCR_WEST, active=False),
            None,
            SKIP_INACTIVE,
            _london(12, 0),
        ),
        (
            "out of hours",
            _london(21, 0),
            _london(21, 0),
            UCR_WEST,
            None,
            SKIP_OUT_OF_HOURS,
            datetime(2026, 10, 24, 7, 0, tzinfo=UTC),  # Saturday 08:00 BST
        ),
        (
            "reply window closed",
            DUE,
            DUE + timedelta(minutes=30),
            UCR_WEST,
            None,
            SKIP_REPLY_WINDOW,
            _london(12, 0),
        ),
    ],
    ids=["suspended", "inactive", "out-of-hours", "reply-window-closed"],
)
async def test_a_skipped_prompt_sends_nothing_and_re_arms_the_next_prompt(
    case: str,
    due: datetime,
    now: datetime,
    profile: ServiceProfile,
    flags: str | None,
    reason: str,
    next_prompt: datetime,
    uow_factory: UnitOfWorkFactory,
    neo4j_driver: AsyncDriver,
    seed_service: Seed,
) -> None:
    service_flags: tuple[ServiceFlag, ...] = ()
    if flags == "suspended":
        service_flags = (
            ServiceFlag(
                service_id="ucr-west",
                code=SERVICE_FLAG_SUSPENDED,
                active=True,
                reason="staffing",
                actor_id="prac-lead-1",
                at=DUE - timedelta(hours=3),
            ),
        )
    await seed_service(profile, flags=service_flags)
    await _seed_people(uow_factory, (_practitioner(1, PHONE_HASH_1),), (_role(1),))
    use_case, _ = _rig(uow_factory, neo4j_driver, now=now)

    result = await use_case.execute(_command(due))

    assert result.sent is False
    assert result.communication_ids == ()
    assert result.skipped_reason == reason
    assert await count_nodes(neo4j_driver, "Communication") == 0
    assert await count_nodes(neo4j_driver, "LinkToken") == 0
    assert [m for m in await _outbox(uow_factory) if m.event_type == "SendMessage"] == []
    [chained] = await _works(uow_factory, "ucr-west")
    assert chained.kind is WorkKind.PROMPT_DUE
    assert chained.status == SCHEDULED
    assert chained.due_at == next_prompt
    assert await count_nodes(neo4j_driver, "AuditEvent") == 1


async def test_a_replay_of_a_skip_does_not_arm_a_second_prompt(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await seed_service(dataclasses.replace(UCR_WEST, active=False))
    use_case, _ = _rig(uow_factory, neo4j_driver)
    await use_case.execute(_command())
    counts = await _counts(neo4j_driver)

    replay = await use_case.execute(_command())

    assert replay.replayed is True
    assert replay.skipped_reason == SKIP_INACTIVE
    assert await _counts(neo4j_driver) == counts


async def test_a_lifted_suspension_does_not_skip_the_prompt(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    lifted = ServiceFlag(
        service_id="ucr-west",
        code=SERVICE_FLAG_SUSPENDED,
        active=False,
        reason="staffing",
        actor_id="prac-lead-1",
        at=DUE - timedelta(hours=3),
    )
    await seed_service(UCR_WEST, flags=(lifted,))
    await _seed_people(uow_factory, (_practitioner(1, PHONE_HASH_1),), (_role(1),))
    use_case, _ = _rig(uow_factory, neo4j_driver)

    assert (await use_case.execute(_command())).sent is True


async def test_a_prompt_one_second_before_its_reply_window_closes_is_sent(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await _seed_one_reporter(uow_factory, seed_service)
    use_case, _ = _rig(uow_factory, neo4j_driver, now=DUE + timedelta(minutes=29, seconds=59))

    assert (await use_case.execute(_command())).sent is True


# --- Reporters, cover, ladders (I, J) ------------------------------------------------------------


async def test_two_reporter_roles_get_two_prompts_and_two_ladders(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await seed_service(UCR_WEST)
    await _seed_people(
        uow_factory,
        (_practitioner(1, PHONE_HASH_1), _practitioner(2, PHONE_HASH_2)),
        (_role(1), _role(2, code=PractitionerRoleCode.COORDINATOR)),
    )
    use_case, _ = _rig(uow_factory, neo4j_driver)

    result = await use_case.execute(_command())

    assert len(result.communication_ids) == 2
    assert len(set(result.communication_ids)) == 2
    rows = await _communication_rows(neo4j_driver)
    assert sorted(row["role"] for row in rows) == ["role-1", "role-2"]
    sends = _sent(await _outbox(uow_factory))
    assert sorted(m.payload["communication_id"] for m in sends) == sorted(result.communication_ids)
    assert await count_nodes(neo4j_driver, "LinkToken") == 2
    for communication_id in result.communication_ids:
        assert len(await _works(uow_factory, communication_id)) == 3
    assert len(await _works(uow_factory, "ucr-west", WorkKind.PROMPT_DUE)) == 1


async def test_the_ladder_and_the_next_prompt_are_scheduled(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await _seed_one_reporter(uow_factory, seed_service)
    await _seed_report(uow_factory)
    use_case, _ = _rig(uow_factory, neo4j_driver)

    result = await use_case.execute(_command())

    [communication_id] = result.communication_ids
    ladder = await _works(uow_factory, communication_id)
    assert [(w.kind, w.due_at, w.status) for w in ladder] == [
        (WorkKind.REMINDER, _london(10, 30), SCHEDULED),
        (WorkKind.PHONE_TASK, _london(11, 0), SCHEDULED),
        (WorkKind.ESCALATE_TO_LEAD, _london(11, 30), SCHEDULED),
    ]
    [next_prompt] = await _works(uow_factory, "ucr-west")
    assert (next_prompt.kind, next_prompt.due_at, next_prompt.status) == (
        WorkKind.PROMPT_DUE,
        _london(12, 0),
        SCHEDULED,
    )
    messages = [m for m in await _outbox(uow_factory) if m.event_type == "ScheduleWork"]
    assert len(messages) == 4
    assert {m.topic for m in messages} == {"scheduled.work"}
    by_work = {m.payload["work_id"]: m.payload for m in messages}
    for work in (*ladder, next_prompt):
        assert by_work[work.id] == {
            "work_id": work.id,
            "kind": work.kind.value,
            "about_id": work.about_id,
            "enqueue_at": work.due_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }


async def test_a_reporter_prompt_ladder_belongs_to_its_communication_not_the_service(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    # J: a reporter's ladder is found by the communication id (the message the reporter got).
    await _seed_one_reporter(uow_factory, seed_service)
    await _seed_report(uow_factory)
    use_case, _ = _rig(uow_factory, neo4j_driver)

    [communication_id] = (await use_case.execute(_command())).communication_ids

    assert await _works(uow_factory, "ucr-west", WorkKind.REMINDER) == []
    [reminder] = await _works(uow_factory, communication_id, WorkKind.REMINDER)
    assert reminder.due_at == _london(10, 30)


async def test_no_textable_reporter_starts_a_ladder_for_the_service(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    # I: nobody can be texted, so the chase is about the service. The lead still gets the step at
    # +90 minutes, and the chain goes on.
    await seed_service(UCR_WEST)
    await _seed_people(uow_factory, (_practitioner(1, None),), (_role(1),))
    use_case, _ = _rig(uow_factory, neo4j_driver)

    result = await use_case.execute(_command())

    assert result.sent is False
    assert result.communication_ids == ()
    assert result.skipped_reason == SKIP_NO_REPORTER
    assert await count_nodes(neo4j_driver, "Communication") == 0
    assert await count_nodes(neo4j_driver, "LinkToken") == 0
    ladder = await _works(uow_factory, "ucr-west")
    assert sorted((w.kind.value, w.due_at) for w in ladder) == sorted(
        [
            (WorkKind.PROMPT_DUE.value, _london(12, 0)),
            (WorkKind.REMINDER.value, _london(10, 30)),
            (WorkKind.PHONE_TASK.value, _london(11, 0)),
            (WorkKind.ESCALATE_TO_LEAD.value, _london(11, 30)),
        ]
    )


async def test_a_service_ladder_is_found_by_service_kind_and_due_time(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    # J: U06 finds a service-level ladder with for_about(service_id, kind), and tells one prompt
    # from the next by due_at (the prompt's due plus the step's offset).
    await seed_service(UCR_WEST)
    await _seed_people(uow_factory, (_practitioner(1, None),), (_role(1),))
    use_case, clock = _rig(uow_factory, neo4j_driver)
    await use_case.execute(_command(DUE))
    clock.set(_london(12, 0))
    await use_case.execute(_command(_london(12, 0)))

    reminders = await _works(uow_factory, "ucr-west", WorkKind.REMINDER)

    assert sorted(w.due_at for w in reminders) == [_london(10, 30), _london(12, 30)]


async def test_cover_sends_the_prompt_to_the_cover_phone(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await seed_service(UCR_WEST)
    covered = _role(1, covered_by_practitioner_id="prac-2", covered_until=DUE + timedelta(hours=4))
    await _seed_people(
        uow_factory,
        (_practitioner(1, PHONE_HASH_1), _practitioner(2, PHONE_HASH_2)),
        (covered,),
    )
    await _seed_report(uow_factory)
    use_case, _ = _rig(uow_factory, neo4j_driver)

    result = await use_case.execute(_command())

    [communication_id] = result.communication_ids
    [row] = await _communication_rows(neo4j_driver)
    assert row["id"] == communication_id
    assert row["role"] == "role-1"
    [message] = _sent(await _outbox(uow_factory))
    record = await _resolve(neo4j_driver, DUE, _token_of(message))
    assert record is not None
    assert record.phone_hash == PHONE_HASH_2


async def test_an_inactive_holder_is_treated_as_no_textable_reporter(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await seed_service(UCR_WEST)
    gone = dataclasses.replace(_practitioner(1, PHONE_HASH_1), active=False)
    await _seed_people(uow_factory, (gone,), (_role(1),))
    use_case, _ = _rig(uow_factory, neo4j_driver)

    result = await use_case.execute(_command())

    assert result.sent is False
    assert result.skipped_reason == SKIP_NO_REPORTER
    assert await count_nodes(neo4j_driver, "Communication") == 0
    assert await count_nodes(neo4j_driver, "LinkToken") == 0


# --- Idempotency and atomicity (C, D) ------------------------------------------------------------


async def test_a_replay_of_the_same_due_time_changes_nothing(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await _seed_one_reporter(uow_factory, seed_service)
    use_case, _ = _rig(uow_factory, neo4j_driver)
    first = await use_case.execute(_command())
    counts = await _counts(neo4j_driver)

    replay = await use_case.execute(_command())

    assert replay == dataclasses.replace(first, replayed=True)
    assert await _counts(neo4j_driver) == counts


async def test_a_reused_key_with_another_body_is_a_conflict(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    # C: the same key with another due time is another command. It is refused, and nothing is
    # written for it.
    await _seed_one_reporter(uow_factory, seed_service)
    await _seed_report(uow_factory)
    use_case, _ = _rig(uow_factory, neo4j_driver)
    await use_case.execute(_command())
    counts = await _counts(neo4j_driver)
    reused = SendPromptCommand(
        idempotency_key=_command().idempotency_key,
        actor=SYSTEM_ACTOR,
        service_id="ucr-west",
        due_at=DUE + timedelta(hours=2),
    )

    with pytest.raises(Conflict):
        await use_case.execute(reused)

    assert await _counts(neo4j_driver) == counts


async def test_a_reused_key_from_another_actor_is_a_conflict(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    # H: DEC-104 fingerprint includes the actor, so the same body from another actor is refused.
    await _seed_one_reporter(uow_factory, seed_service)
    use_case, _ = _rig(uow_factory, neo4j_driver)
    await use_case.execute(_command())
    other_actor = Actor(
        role=Role.LEAD,
        practitioner_id="prac-lead-1",
        device_id=None,
        channel="web",
        service_ids=frozenset(),
    )
    same_body = dataclasses.replace(_command(), actor=other_actor)

    with pytest.raises(Conflict):
        await use_case.execute(same_body)


async def test_a_failure_after_the_writes_leaves_nothing_behind(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    # D: the audit append is the last write. Its failure must roll back the communication, the
    # token, the outbox messages, the ladder, the next prompt and the idempotency record.
    await _seed_one_reporter(uow_factory, seed_service)
    await _seed_report(uow_factory)
    before = await _counts(neo4j_driver)

    def failing() -> _FailingAuditUnitOfWork:
        return _FailingAuditUnitOfWork(uow_factory())

    use_case, _ = _rig(failing, neo4j_driver)  # type: ignore[arg-type]
    with pytest.raises(RuntimeError, match="audit write failed"):
        await use_case.execute(_command())

    assert await _counts(neo4j_driver) == before
    assert await count_nodes(neo4j_driver, "Communication") == 0
    async with uow_factory() as uow:
        assert await uow.idempotency.get(_command().idempotency_key) is None


async def test_a_profile_with_no_next_due_instant_is_refused_and_writes_nothing(
    uow_factory: UnitOfWorkFactory,
    neo4j_driver: AsyncDriver,
    seed_service: Seed,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The next prompt cannot be armed. A valid profile always has one (every window yields due
    # times), so this is refused rather than sent without a chain (DEC-115 item 29).
    await _seed_one_reporter(uow_factory, seed_service)
    before = await _counts(neo4j_driver)
    monkeypatch.setattr(send_prompts_module, "next_due", lambda profile, now: None)
    use_case, _ = _rig(uow_factory, neo4j_driver)

    with pytest.raises(DomainError):
        await use_case.execute(_command())

    assert await _counts(neo4j_driver) == before


async def test_a_replay_seen_only_inside_the_unit_of_work_is_still_a_replay(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    # A race: the early read outside the unit of work misses the record another writer made. The
    # check inside the unit of work must still answer with the stored result, and write nothing
    # (DEC-106 item 2). After the fact: the code passed this test when it was written.
    await _seed_one_reporter(uow_factory, seed_service)
    first_use_case, _ = _rig(uow_factory, neo4j_driver)
    first = await first_use_case.execute(_command())
    counts = await _counts(neo4j_driver)

    class _MissesTheEarlyRead:
        def __init__(self, inner: DriverIdempotencyStore) -> None:
            self._inner = inner
            self._missed = False

        async def get(self, key: str) -> Any:
            if not self._missed:
                self._missed = True
                return None
            return await self._inner.get(key)

        async def put(self, key: str, result: object) -> None:
            await self._inner.put(key, result)

    clock = FixedClock(DUE)

    def tokens(repo: LinkTokenRepository) -> LinkTokenService:
        return LinkTokenService(repo, FixedSecretStore({"link-token": SECRET}), clock)

    racing = SendPrompts(
        uow_factory,
        clock,
        SequentialIds(),
        _MissesTheEarlyRead(DriverIdempotencyStore(neo4j_driver)),  # type: ignore[arg-type]
        tokens,
        LINK_BASE,
        FixedSecretStore({"link-token": SECRET}),
        TENANT,
    )

    replay = await racing.execute(_command())

    assert replay == dataclasses.replace(first, replayed=True)
    assert await _counts(neo4j_driver) == counts


async def test_an_unknown_service_is_refused(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await seed_service(UCR_WEST)
    use_case, _ = _rig(uow_factory, neo4j_driver)

    with pytest.raises(NotFound):
        await use_case.execute(_command(service_id="no-such-service"))


async def test_a_due_time_without_a_timezone_is_refused(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await _seed_one_reporter(uow_factory, seed_service)
    use_case, _ = _rig(uow_factory, neo4j_driver)
    naive = SendPromptCommand("key-naive", SYSTEM_ACTOR, "ucr-west", datetime(2026, 10, 23, 9, 0))

    with pytest.raises(ValidationFailed):
        await use_case.execute(naive)

    assert await count_nodes(neo4j_driver, "Communication") == 0
    assert await count_nodes(neo4j_driver, "ScheduledWork") == 0


async def test_the_next_due_time_is_a_separate_prompt(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await _seed_one_reporter(uow_factory, seed_service)
    use_case, clock = _rig(uow_factory, neo4j_driver)
    await use_case.execute(_command())
    clock.set(DUE + timedelta(hours=2))

    second = await use_case.execute(_command(DUE + timedelta(hours=2)))

    assert second.sent is True
    assert second.replayed is False
    assert await count_nodes(neo4j_driver, "Communication") == 2


# --- Scheduling helpers (E, the cancel rules) ----------------------------------------------------


async def test_schedule_work_writes_the_row_and_the_outbox_message(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver
) -> None:
    due = datetime(2026, 10, 23, 11, 0, tzinfo=UTC)
    async with uow_factory() as uow:
        work = await schedule_work(
            uow, SequentialIds("w"), kind=WorkKind.REMINDER, about_id="comm-1", due_at=due, now=DUE
        )
        await uow.commit()

    assert work.status == SCHEDULED
    assert work.sequence_number is None
    assert (work.kind, work.about_id, work.due_at) == (WorkKind.REMINDER, "comm-1", due)
    async with uow_factory() as uow:
        assert await uow.scheduled_work.get(work.id) == work
    [message] = await _outbox(uow_factory)
    assert (message.topic, message.event_type) == ("scheduled.work", "ScheduleWork")
    assert message.payload == {
        "work_id": work.id,
        "kind": "reminder",
        "about_id": "comm-1",
        "enqueue_at": "2026-10-23T11:00:00Z",
    }
    assert message.created_at == DUE


async def test_schedule_work_reads_a_london_wall_time_through_its_offset(
    uow_factory: UnitOfWorkFactory,
) -> None:
    # E: 01:30 London on 2026-10-25 is BST (UTC+1), so the instant is 00:30Z. Read as UTC, the
    # same wall time would be 01:30Z. The summer case below fails the same way.
    local = datetime(2026, 10, 25, 1, 30, tzinfo=LONDON, fold=0)
    summer = datetime(2026, 10, 23, 10, 0, tzinfo=LONDON)
    async with uow_factory() as uow:
        first = await schedule_work(
            uow, SequentialIds("w"), kind=WorkKind.REMINDER, about_id="c-1", due_at=local, now=DUE
        )
        second = await schedule_work(
            uow, SequentialIds("v"), kind=WorkKind.REMINDER, about_id="c-2", due_at=summer, now=DUE
        )
        await uow.commit()

    assert first.due_at == datetime(2026, 10, 25, 0, 30, tzinfo=UTC)
    assert second.due_at == datetime(2026, 10, 23, 9, 0, tzinfo=UTC)
    enqueue = sorted(m.payload["enqueue_at"] for m in await _outbox(uow_factory))
    assert enqueue == ["2026-10-23T09:00:00Z", "2026-10-25T00:30:00Z"]


async def test_schedule_work_refuses_a_naive_due_time(uow_factory: UnitOfWorkFactory) -> None:
    async with uow_factory() as uow:
        with pytest.raises(ValidationFailed):
            await schedule_work(
                uow,
                SequentialIds("w"),
                kind=WorkKind.REMINDER,
                about_id="comm-1",
                due_at=datetime(2026, 10, 23, 11, 0),
                now=DUE,
            )


async def test_cancel_work_marks_the_row_cancelled_and_queues_a_cancel(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver
) -> None:
    async with uow_factory() as uow:
        work = await schedule_work(
            uow,
            SequentialIds("w"),
            kind=WorkKind.BOOKING_EXPIRE,
            about_id="booking-1",
            due_at=DUE + timedelta(minutes=10),
            now=DUE,
        )
        await uow.commit()

    async with uow_factory() as uow:
        await cancel_work(uow, work, DUE + timedelta(minutes=1))
        await uow.commit()

    async with uow_factory() as uow:
        stored = await uow.scheduled_work.get(work.id)
    assert stored.status == CANCELLED
    assert (stored.kind, stored.about_id, stored.due_at) == (work.kind, work.about_id, work.due_at)
    cancels = [m for m in await _outbox(uow_factory) if m.event_type == "CancelWork"]
    assert len(cancels) == 1
    assert cancels[0].topic == "scheduled.work"
    assert cancels[0].payload == {"work_id": work.id}
    assert cancels[0].created_at == DUE + timedelta(minutes=1)


async def test_cancel_work_keeps_the_sequence_number_the_relay_stored(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver
) -> None:
    async with uow_factory() as uow:
        work = await schedule_work(
            uow, SequentialIds("w"), kind=WorkKind.REVERIFY, about_id="p-1", due_at=DUE, now=DUE
        )
        await uow.scheduled_work.save(dataclasses.replace(work, sequence_number=42))
        await uow.commit()

    async with uow_factory() as uow:
        await cancel_work(uow, work, DUE)  # a stale copy, without the sequence number
        await uow.commit()

    async with uow_factory() as uow:
        stored = await uow.scheduled_work.get(work.id)
    assert (stored.status, stored.sequence_number) == (CANCELLED, 42)


@pytest.mark.parametrize("status", ["done", "cancelled"])
async def test_cancel_work_does_nothing_for_work_that_is_not_scheduled(
    status: str, uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver
) -> None:
    async with uow_factory() as uow:
        work = await schedule_work(
            uow, SequentialIds("w"), kind=WorkKind.REVERIFY, about_id="p-1", due_at=DUE, now=DUE
        )
        await uow.scheduled_work.save(dataclasses.replace(work, status=status))
        await uow.commit()
    before = await count_nodes(neo4j_driver, "OutboxMessage")

    async with uow_factory() as uow:
        await cancel_work(uow, work, DUE)
        await uow.commit()

    async with uow_factory() as uow:
        assert (await uow.scheduled_work.get(work.id)).status == status
    assert await count_nodes(neo4j_driver, "OutboxMessage") == before
