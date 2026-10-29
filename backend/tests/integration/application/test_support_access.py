"""Support access, end to end against Neo4j (O06, the acceptance tests of the task).

Each test runs its use cases in the run tenant (conftest binds it). Two practitioners and one
reporter session are seeded in that tenant with plain Cypher, which is test setup only. Synthetic
values only. Written in the build wave and run in the verification stage (one Neo4j at a time).
"""

from datetime import UTC, datetime, timedelta

import pytest
from neo4j import AsyncDriver

from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_ids import SequentialIds
from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.application.actor import Actor
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.use_cases.support_access import (
    CreateSupportCode,
    CreateSupportCodeCommand,
    ListMyAccesses,
    ListMyAccessesCommand,
    OpenSessionCommand,
    OpenSessionForSupport,
    StopSharing,
    StopSharingCommand,
)
from diucs.domain.codes import PractitionerRoleCode, Role
from diucs.domain.errors import NotAllowed
from diucs.domain.model.people import Practitioner, PractitionerRole
from diucs.domain.rules.support import hash_support_code, normalise_support_code
from tests.support.neo4j import count_nodes, read_tx
from tests.support.uow import ensure_audit_heads

pytestmark = pytest.mark.asyncio(loop_scope="session")

NOW = datetime(2026, 10, 29, 9, 0, tzinfo=UTC)
SECRET = b"support-code-integration-secret-0123"
SECRETS = FixedSecretStore({"support-code": SECRET})


async def _seed(driver: AsyncDriver, factory: UnitOfWorkFactory, tenant: str) -> None:
    """Two practitioners: `p-reporter` shares a session, `p-lead` holds an active shift-lead role,
    `p-support` is the support person. Plus the reporter's session, with no person link. The people
    are written through the person repository: the product reads them as FHIR resources, so plain
    nodes would not be found."""
    await ensure_audit_heads(driver, tenant)
    async with factory() as uow:
        for practitioner_id, name in (
            ("p-reporter", "Sample Reporter"),
            ("p-lead", "Sample Lead"),
            ("p-support", "Sample Support"),
        ):
            await uow.people.save_practitioner(
                Practitioner(id=practitioner_id, active=True, display_name=name, phone_hash=None)
            )
        await uow.people.save_role(
            PractitionerRole(
                id="r-lead",
                practitioner_id="p-lead",
                service_id=None,
                code=PractitionerRoleCode.SHIFT_LEAD,
                active=True,
                channel=None,
                period_start=NOW - timedelta(days=30),
            )
        )
        await uow.commit()


def _actor(role: Role, practitioner: str | None) -> Actor:
    return Actor(
        role=role,
        practitioner_id=practitioner,
        device_id=None,
        channel="web",
        service_ids=frozenset(),
    )


async def _create_code(uow_factory: UnitOfWorkFactory, session_id: str) -> str:
    result = await CreateSupportCode(
        uow_factory, FixedClock(NOW), SequentialIds(), SECRETS
    ).execute(
        CreateSupportCodeCommand(
            actor=_actor(Role.REPORTER, "p-reporter"),
            session_id=session_id,
            device_type="phone",
            app_mode="browser",
            release="2026.10.29",
        )
    )
    return result.code


async def test_creating_a_code_returns_the_xxxx_xxxx_form(
    clean_graph: None, neo4j_driver: AsyncDriver, uow_factory_a: UnitOfWorkFactory, tenant_id: str
) -> None:
    await _seed(neo4j_driver, uow_factory_a, tenant_id)

    code = await _create_code(uow_factory_a, "ui-1")

    assert len(code) == 9 and code[4] == "-"
    assert normalise_support_code(code) == code


async def test_the_stored_code_holds_only_its_hash(
    clean_graph: None, neo4j_driver: AsyncDriver, uow_factory_a: UnitOfWorkFactory, tenant_id: str
) -> None:
    await _seed(neo4j_driver, uow_factory_a, tenant_id)
    code = await _create_code(uow_factory_a, "ui-1")

    async def props(tx: object) -> list[dict[str, object]]:
        result = await tx.run(
            "MATCH (c:SupportCode {tenantId: $t}) RETURN properties(c) AS p", t=tenant_id
        )  # type: ignore[attr-defined]
        return [dict(row["p"]) for row in await result.data()]  # type: ignore[call-overload]

    stored = await read_tx(neo4j_driver, props)
    assert len(stored) == 1
    assert stored[0]["codeHash"] == hash_support_code(code, SECRET)
    assert code not in str(stored[0].values())


async def test_an_open_with_the_code_writes_one_access_with_an_hour_window_and_one_audit_entry(
    clean_graph: None, neo4j_driver: AsyncDriver, uow_factory_a: UnitOfWorkFactory, tenant_id: str
) -> None:
    await _seed(neo4j_driver, uow_factory_a, tenant_id)
    code = await _create_code(uow_factory_a, "ui-1")

    result = await OpenSessionForSupport(
        uow_factory_a, FixedClock(NOW), SequentialIds(), SECRETS
    ).execute(OpenSessionCommand(actor=_actor(Role.SUPPORT, "p-support"), code=code))

    assert result.expires_at == NOW + timedelta(hours=1)
    assert await count_nodes(neo4j_driver, "SupportAccess") == 1
    assert await count_nodes(neo4j_driver, "AuditEntry") >= 1


async def test_an_expired_or_wrong_code_is_refused_with_the_same_error(
    clean_graph: None, neo4j_driver: AsyncDriver, uow_factory_a: UnitOfWorkFactory, tenant_id: str
) -> None:
    await _seed(neo4j_driver, uow_factory_a, tenant_id)
    code = await _create_code(uow_factory_a, "ui-1")
    wrong = "ABCD-EFGH" if code != "ABCD-EFGH" else "ABCD-EFGK"
    later = FixedClock(NOW + timedelta(hours=5))
    support = _actor(Role.SUPPORT, "p-support")

    with pytest.raises(NotAllowed) as wrong_error:
        await OpenSessionForSupport(
            uow_factory_a, FixedClock(NOW), SequentialIds(), SECRETS
        ).execute(OpenSessionCommand(actor=support, code=wrong))
    with pytest.raises(NotAllowed) as expired_error:
        await OpenSessionForSupport(uow_factory_a, later, SequentialIds(), SECRETS).execute(
            OpenSessionCommand(actor=support, code=code)
        )

    assert str(wrong_error.value) == str(expired_error.value)


async def test_a_ticket_without_a_lead_approval_is_refused_and_with_one_is_allowed(
    clean_graph: None, neo4j_driver: AsyncDriver, uow_factory_a: UnitOfWorkFactory, tenant_id: str
) -> None:
    await _seed(neo4j_driver, uow_factory_a, tenant_id)
    await _create_code(uow_factory_a, "ui-1")
    open_session = OpenSessionForSupport(uow_factory_a, FixedClock(NOW), SequentialIds(), SECRETS)
    support = _actor(Role.SUPPORT, "p-support")

    with pytest.raises(NotAllowed):
        await open_session.execute(
            OpenSessionCommand(
                actor=support, session_id="ui-1", ticket="INC-1001", approved_by="p-reporter"
            )
        )
    result = await open_session.execute(
        OpenSessionCommand(
            actor=support, session_id="ui-1", ticket="INC-1001", approved_by="p-lead"
        )
    )

    assert result.session_id == "ui-1"


async def test_an_advisor_trying_to_open_a_session_is_refused(
    clean_graph: None, neo4j_driver: AsyncDriver, uow_factory_a: UnitOfWorkFactory, tenant_id: str
) -> None:
    await _seed(neo4j_driver, uow_factory_a, tenant_id)
    code = await _create_code(uow_factory_a, "ui-1")

    with pytest.raises(NotAllowed):
        await OpenSessionForSupport(
            uow_factory_a, FixedClock(NOW), SequentialIds(), SECRETS
        ).execute(OpenSessionCommand(actor=_actor(Role.ADVISOR, "p-reporter"), code=code))


async def test_the_person_lists_each_open_with_the_role_and_time_and_never_a_name(
    clean_graph: None, neo4j_driver: AsyncDriver, uow_factory_a: UnitOfWorkFactory, tenant_id: str
) -> None:
    await _seed(neo4j_driver, uow_factory_a, tenant_id)
    code = await _create_code(uow_factory_a, "ui-1")
    await OpenSessionForSupport(uow_factory_a, FixedClock(NOW), SequentialIds(), SECRETS).execute(
        OpenSessionCommand(actor=_actor(Role.SUPPORT, "p-support"), code=code)
    )

    views = await ListMyAccesses(uow_factory_a, FixedClock(NOW)).execute(
        ListMyAccessesCommand(actor=_actor(Role.REPORTER, "p-reporter"), session_id="ui-1")
    )

    assert [view.by for view in views] == [Role.SUPPORT.value]
    assert views[0].opened_at == NOW
    assert "Sample Support" not in repr(views)


async def test_after_stop_sharing_the_code_no_longer_opens_anything(
    clean_graph: None, neo4j_driver: AsyncDriver, uow_factory_a: UnitOfWorkFactory, tenant_id: str
) -> None:
    await _seed(neo4j_driver, uow_factory_a, tenant_id)
    code = await _create_code(uow_factory_a, "ui-1")
    await StopSharing(uow_factory_a, FixedClock(NOW)).execute(
        StopSharingCommand(actor=_actor(Role.REPORTER, "p-reporter"), session_id="ui-1")
    )

    with pytest.raises(NotAllowed):
        await OpenSessionForSupport(
            uow_factory_a, FixedClock(NOW), SequentialIds(), SECRETS
        ).execute(OpenSessionCommand(actor=_actor(Role.SUPPORT, "p-support"), code=code))
