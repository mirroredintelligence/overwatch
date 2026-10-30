"""The tenant registry's writes without a database (TEN-028, DEC-503): what each call sends, what it
refuses to send, and what it does with the answers.

The connection is a recording stand-in (`tests/support/registry_connection.py`). The behaviour on a
real Neo4j, with two tenants, is `tests/integration/graph_store/test_tenant_registry.py`.
"""

from datetime import UTC, datetime
from typing import Any, cast

import pytest
from neo4j.exceptions import ConstraintError
from neo4j.time import DateTime

from diucs.adapters.outbound.graph_store.connection import Neo4jConnection
from diucs.adapters.outbound.graph_store.tenant_registry import (
    Neo4jTenantRegistry,
    number_from_row,
    number_properties,
    tenant_write_properties,
)
from diucs.application.ports.outbound.tenant_registry import TenantNumberRecord
from diucs.application.ports.outbound.tenants import TenantRecordInvalid, twilio_token_ref
from diucs.domain.errors import Conflict, NotFound, ValidationFailed
from diucs.domain.model.tenant import NumberStatus, SuspendMode, SuspendReason, TenantStatus
from diucs.domain.rules.tenant_lifecycle import resume_tenant, suspend_tenant
from tests.support.registry_connection import RecordingWriteConnection
from tests.support.tenant_samples import SAMPLE_ID, T0, make_tenant

SID = "AC" + "1" * 32
NUMBER = "+447700900123"
NOW = datetime(2026, 10, 30, 9, 0, tzinfo=UTC)


def _registry(connection: RecordingWriteConnection) -> Neo4jTenantRegistry:
    return Neo4jTenantRegistry(cast(Neo4jConnection, connection))


def _number(**fields: Any) -> TenantNumberRecord:
    base: dict[str, Any] = {
        "e164": NUMBER,
        "account_sid": SID,
        "secret_ref": twilio_token_ref(SAMPLE_ID),
    }
    return TenantNumberRecord(**{**base, **fields})


# -- create --------------------------------------------------------------------------------------


async def test_create_sends_the_id_and_every_property_but_the_id() -> None:
    connection = RecordingWriteConnection({"Q-TENANT-REG-CREATE": [{"id": SAMPLE_ID}]})
    tenant = make_tenant(TenantStatus.PROVISIONING)

    await _registry(connection).create(tenant)

    [(query_id, kind, parameters)] = connection.calls
    assert (query_id, kind) == ("Q-TENANT-REG-CREATE", "write")
    assert set(parameters) == {"id", "props"}
    assert parameters["id"] == SAMPLE_ID
    assert "id" not in parameters["props"] and "tenantId" not in parameters["props"]
    assert parameters["props"]["status"] == "provisioning"
    assert parameters["props"]["epoch"] == 1


async def test_a_tenant_that_is_not_provisioning_is_not_created() -> None:
    connection = RecordingWriteConnection()
    with pytest.raises(ValidationFailed):
        await _registry(connection).create(make_tenant(TenantStatus.ACTIVE))
    assert connection.calls == []


async def test_an_id_that_exists_is_a_conflict_with_a_fixed_message() -> None:
    connection = RecordingWriteConnection({"Q-TENANT-REG-CREATE": ConstraintError("tenant_id")})
    with pytest.raises(Conflict) as refused:
        await _registry(connection).create(make_tenant(TenantStatus.PROVISIONING))
    assert SAMPLE_ID not in str(refused.value)


# -- the properties a save writes ----------------------------------------------------------------


def test_a_save_writes_none_for_a_property_that_is_not_set() -> None:
    suspended = suspend_tenant(
        make_tenant(), SuspendMode.READ_ONLY, SuspendReason.OPERATOR_REQUEST, T0.replace(year=2027)
    )
    props = tenant_write_properties(suspended)
    assert props["status"] == "suspended" and props["suspendMode"] == "read-only"

    resumed = tenant_write_properties(resume_tenant(suspended, T0.replace(year=2028)))
    # None, not absent: `SET t += $props` removes a property set to None, so a resumed tenant has
    # no suspend fields left on its node.
    assert resumed["suspendMode"] is None
    assert resumed["suspendReason"] is None
    assert resumed["suspendedAt"] is None
    assert resumed["status"] == "active"
    assert resumed["epoch"] == suspended.epoch + 1


def test_a_save_never_writes_the_id_the_host_or_the_directory() -> None:
    props = tenant_write_properties(make_tenant())
    assert not {"id", "host", "entraDirectoryId", "tenantId"} & set(props)


# -- save (compare and set) ----------------------------------------------------------------------


async def test_a_save_is_a_compare_and_set_on_the_epoch_and_status_as_read() -> None:
    connection = RecordingWriteConnection({"Q-TENANT-REG-SAVE": [{"id": SAMPLE_ID}]})
    tenant = make_tenant()

    saved = await _registry(connection).save(
        tenant, expected_epoch=3, expected_status=TenantStatus.PROVISIONING
    )

    assert saved is True
    [(_, _, parameters)] = connection.calls
    assert parameters["expectedEpoch"] == 3
    assert parameters["expectedStatus"] == "provisioning"
    assert parameters["id"] == SAMPLE_ID


async def test_a_save_that_matches_nothing_answers_false() -> None:
    connection = RecordingWriteConnection({"Q-TENANT-REG-SAVE": []})
    assert (
        await _registry(connection).save(
            make_tenant(), expected_epoch=1, expected_status=TenantStatus.ACTIVE
        )
        is False
    )


# -- host and directory --------------------------------------------------------------------------


async def test_the_host_is_sent_in_its_lookup_form() -> None:
    connection = RecordingWriteConnection({"Q-TENANT-REG-SET-HOST": [{"id": SAMPLE_ID}]})
    await _registry(connection).set_host(SAMPLE_ID, "Acme.Example.ORG.")
    [(_, _, parameters)] = connection.calls
    assert parameters == {"id": SAMPLE_ID, "host": "acme.example.org"}


@pytest.mark.parametrize("bad", ["", "not a host", "a_b.example", "x" * 300, "https://a.example"])
async def test_a_host_that_is_not_a_host_name_sends_nothing(bad: str) -> None:
    connection = RecordingWriteConnection()
    with pytest.raises(ValidationFailed):
        await _registry(connection).set_host(SAMPLE_ID, bad)
    assert connection.calls == []


async def test_a_host_another_tenant_holds_is_a_conflict() -> None:
    connection = RecordingWriteConnection({"Q-TENANT-REG-SET-HOST": ConstraintError("host")})
    with pytest.raises(Conflict):
        await _registry(connection).set_host(SAMPLE_ID, "acme.example.org")


async def test_a_host_for_a_tenant_that_does_not_exist_is_not_found() -> None:
    connection = RecordingWriteConnection({"Q-TENANT-REG-SET-HOST": []})
    with pytest.raises(NotFound):
        await _registry(connection).set_host(SAMPLE_ID, "acme.example.org")


async def test_the_directory_is_sent_in_lower_case_and_a_bad_one_sends_nothing() -> None:
    guid = "0F5A7C1E-3B2D-4C6A-9E8F-1A2B3C4D5E6F"
    connection = RecordingWriteConnection({"Q-TENANT-REG-SET-DIRECTORY": [{"id": SAMPLE_ID}]})
    await _registry(connection).set_entra_directory(SAMPLE_ID, guid)
    assert connection.calls[0][2] == {"id": SAMPLE_ID, "directoryId": guid.lower()}
    with pytest.raises(ValidationFailed):
        await _registry(connection).set_entra_directory(SAMPLE_ID, "not-a-guid")
    assert len(connection.calls) == 1


async def test_a_tenant_id_that_is_not_a_tenant_id_sends_nothing() -> None:
    connection = RecordingWriteConnection()
    registry = _registry(connection)
    for bad in ("", "platform", "net-west", "A", "a/b"):
        with pytest.raises(ValidationFailed):
            await registry.set_host(bad, "acme.example.org")
        with pytest.raises(ValidationFailed):
            await registry.numbers(bad)
    assert connection.calls == []


# -- numbers -------------------------------------------------------------------------------------


async def test_a_number_is_put_with_the_properties_of_its_node_and_no_token() -> None:
    connection = RecordingWriteConnection({"Q-TENANT-REG-PUT-NUMBER": [{"e164": NUMBER}]})
    await _registry(connection).put_number(SAMPLE_ID, _number())
    [(_, _, parameters)] = connection.calls
    assert parameters["id"] == SAMPLE_ID and parameters["e164"] == NUMBER
    assert parameters["props"] == {
        "accountSid": SID,
        "secretRef": f"twilio/{SAMPLE_ID}/auth-token",
        "status": "active",
        "testedAt": None,
        "quarantineUntil": None,
    }


async def test_a_number_that_points_at_another_tenants_secret_is_refused_before_a_write() -> None:
    connection = RecordingWriteConnection()
    other = _number(secret_ref="twilio/other-org/auth-token")
    with pytest.raises(ValidationFailed):
        await _registry(connection).put_number(SAMPLE_ID, other)
    assert connection.calls == []


async def test_a_number_another_tenant_holds_is_a_conflict_not_a_move() -> None:
    connection = RecordingWriteConnection(
        {"Q-TENANT-REG-PUT-NUMBER": ConstraintError("tenant_number_e164")}
    )
    with pytest.raises(Conflict):
        await _registry(connection).put_number(SAMPLE_ID, _number())


async def test_a_number_for_a_tenant_that_does_not_exist_is_not_found() -> None:
    connection = RecordingWriteConnection({"Q-TENANT-REG-PUT-NUMBER": []})
    with pytest.raises(NotFound):
        await _registry(connection).put_number(SAMPLE_ID, _number())


async def test_a_test_text_is_marked_on_the_tenants_own_number_only() -> None:
    connection = RecordingWriteConnection({"Q-TENANT-REG-MARK-TESTED": [{"e164": NUMBER}]})
    await _registry(connection).mark_number_tested(SAMPLE_ID, NUMBER, NOW)
    assert connection.calls[0][2] == {"id": SAMPLE_ID, "e164": NUMBER, "at": NOW}

    connection = RecordingWriteConnection({"Q-TENANT-REG-MARK-TESTED": []})
    with pytest.raises(NotFound):
        await _registry(connection).mark_number_tested(SAMPLE_ID, NUMBER, NOW)


async def test_a_naive_instant_or_a_bad_number_is_refused_before_a_write() -> None:
    connection = RecordingWriteConnection()
    with pytest.raises(ValidationFailed):
        await _registry(connection).mark_number_tested(SAMPLE_ID, NUMBER, datetime(2026, 1, 1))
    with pytest.raises(ValidationFailed):
        await _registry(connection).mark_number_tested(SAMPLE_ID, "07700900123", NOW)
    assert connection.calls == []


async def test_the_numbers_are_read_through_the_platform_read() -> None:
    row = {
        "e164": NUMBER,
        "accountSid": SID,
        "secretRef": twilio_token_ref(SAMPLE_ID),
        "status": "active",
        "testedAt": DateTime.from_native(NOW),
        "quarantineUntil": None,
    }
    connection = RecordingWriteConnection({"Q-TENANT-REG-NUMBERS": [row]})

    [number] = await _registry(connection).numbers(SAMPLE_ID)

    assert connection.calls[0][1] == "read"
    assert number == _number(tested_at=NOW)
    assert number.status is NumberStatus.ACTIVE


def test_a_row_that_is_not_a_valid_number_is_a_fixed_configuration_fault() -> None:
    good = {
        "e164": NUMBER,
        "accountSid": SID,
        "secretRef": twilio_token_ref(SAMPLE_ID),
        "status": "active",
        "testedAt": None,
        "quarantineUntil": None,
    }
    assert number_from_row(good, SAMPLE_ID).e164 == NUMBER
    for broken in (
        {**good, "e164": "0770"},
        {**good, "accountSid": "AC1"},
        {**good, "status": "lost"},
        {**good, "secretRef": "twilio/other-org/auth-token"},
        {**good, "testedAt": "yesterday"},
        {k: v for k, v in good.items() if k != "status"},
    ):
        with pytest.raises(TenantRecordInvalid) as refused:
            number_from_row(broken, SAMPLE_ID)
        assert NUMBER not in str(refused.value) and SAMPLE_ID not in str(refused.value)


def test_a_number_record_checks_itself() -> None:
    with pytest.raises(ValidationFailed):
        _number(e164="12345")
    with pytest.raises(ValidationFailed):
        _number(account_sid="x")
    with pytest.raises(ValidationFailed):
        _number(status="active")
    with pytest.raises(ValidationFailed):
        _number(tested_at=datetime(2026, 1, 1))
    assert number_properties(_number(status=NumberStatus.RETIRED))["status"] == "retired"
