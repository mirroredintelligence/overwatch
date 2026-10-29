"""The tenant directory without a database (TEN-007): what it sends, what it refuses to send, and
what it does with the rows it gets back.

The connection is a recording stand-in (`tests/support/directory_connection.py`). The behaviour on
a real Neo4j, with two tenants and a graph that also holds data, is
`tests/integration/graph_store/test_tenant_directory.py`.
"""

import logging
from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any, cast

import pytest
from neo4j.time import DateTime

from diucs.adapters.outbound.graph_store.connection import Neo4jConnection
from diucs.adapters.outbound.graph_store.tenant_directory import (
    Neo4jTenantDirectory,
    tenant_from_properties,
    tenant_properties,
)
from diucs.application.ports.outbound.tenants import TenantRecordInvalid, twilio_token_ref
from diucs.application.tenancy import bind_tenant
from diucs.domain.model.tenant import (
    OrganisationType,
    SuspendMode,
    SuspendReason,
    Tenant,
    TenantStatus,
)
from tests.support.directory_connection import RecordingConnection
from tests.support.tenant_samples import T0, make_tenant

SID = "AC" + "1" * 32
OTHER_SID = "AC" + "2" * 32
NUMBER = "+447700900123"
HOST = "acme.example.org"
GUID = "0f5a7c1e-3b2d-4c6a-9e8f-1a2b3c4d5e6f"

ALL_STATUSES = list(TenantStatus)


def _as_stored(props: Mapping[str, Any]) -> dict[str, Any]:
    """What the driver hands back for the properties of a node: a datetime comes back as a Neo4j
    DateTime."""
    return {
        key: DateTime.from_native(value) if isinstance(value, datetime) else value
        for key, value in props.items()
    }


def _row(tenant: Tenant, **extra: Any) -> dict[str, Any]:
    return {"tenant": _as_stored(tenant_properties(tenant)), **extra}


_OWN_REF = object()


def _line_row(
    tenant: Tenant, *, number: str = NUMBER, sid: str = SID, ref: Any = _OWN_REF
) -> dict[str, Any]:
    reference = twilio_token_ref(tenant.id) if ref is _OWN_REF else ref
    return _row(tenant, number=number, accountSid=sid, secretRef=reference)


def _directory(connection: RecordingConnection) -> Neo4jTenantDirectory:
    return Neo4jTenantDirectory(cast(Neo4jConnection, connection))


def _full_tenant() -> Tenant:
    return make_tenant(
        TenantStatus.ACTIVE,
        id="example-icb",
        ods_code="R1A",
        epoch=5,
        hash_key_version=0,
        current_config_version=3,
        retention_hold_until=T0 + timedelta(days=400),
        dsa_ref="DSA-2026-04 v2",
        dpia_ref="DPIA-17",
        dcb0160_ref="DCB0160/9",
        country_code="GB",
    )


# The record and its node


@pytest.mark.parametrize("status", ALL_STATUSES)
def test_a_tenant_in_any_status_comes_back_from_its_node_equal(status: TenantStatus) -> None:
    tenant = make_tenant(status)
    assert tenant_from_properties(_as_stored(tenant_properties(tenant))) == tenant


def test_a_tenant_with_every_field_set_comes_back_equal() -> None:
    tenant = _full_tenant()
    assert tenant_from_properties(_as_stored(tenant_properties(tenant))) == tenant


def test_the_node_holds_typed_values_and_no_unset_field() -> None:
    props = tenant_properties(make_tenant(TenantStatus.ACTIVE))
    assert set(props) == {
        "id",
        "displayName",
        "legalName",
        "organisationType",
        "countryCode",
        "timeZone",
        "status",
        "createdAt",
        "activatedAt",
        "epoch",
        "hashKeyVersion",
    }
    assert props["status"] == "active" and type(props["status"]) is str
    assert props["organisationType"] == "icb" and type(props["organisationType"]) is str
    assert isinstance(props["createdAt"], datetime) and props["createdAt"].tzinfo is not None
    assert type(props["epoch"]) is int
    assert all(value is not None for value in props.values())


def test_a_suspended_tenant_stores_its_mode_and_reason_as_codes() -> None:
    props = tenant_properties(make_tenant(TenantStatus.SUSPENDED))
    assert props["suspendMode"] == SuspendMode.READ_ONLY.value
    assert props["suspendReason"] == SuspendReason.CONTRACT.value
    assert type(props["suspendMode"]) is str and type(props["suspendReason"]) is str


def test_the_node_holds_no_value_that_is_a_map_a_list_or_a_json_string() -> None:
    for status in ALL_STATUSES:
        for value in tenant_properties(make_tenant(status)).values():
            assert not isinstance(value, dict | list | tuple | set)
            assert not (isinstance(value, str) and value.lstrip()[:1] in "{[")


@pytest.mark.parametrize(
    "damage",
    [
        {"status": "weird"},
        {"status": TenantStatus.ACTIVE},  # an enum object is not what a node holds
        {"organisationType": "company"},
        {"createdAt": "2026-01-05T09:00:00Z"},  # a time stored as text
        {"createdAt": datetime(2026, 1, 5, 9, 0)},  # a naive time
        {"epoch": "1"},
        {"epoch": True},
        {"epoch": 0},
        {"hashKeyVersion": 2},
        {"id": "Not A Tenant"},
        {"id": "platform"},
        {"timeZone": "America/New_York"},
        {"displayName": ""},
        {"id": None},
    ],
)
def test_a_node_the_domain_refuses_is_a_record_fault_that_repeats_no_value(
    damage: dict[str, Any],
) -> None:
    props = _as_stored(tenant_properties(make_tenant(TenantStatus.ACTIVE)))
    props.update(damage)
    with pytest.raises(TenantRecordInvalid) as raised:
        tenant_from_properties(props)
    text = str(raised.value)
    for value in damage.values():
        assert value is None or str(value) not in text
    assert "example-icb" not in text and "Example" not in text


def test_a_node_missing_a_required_property_is_a_record_fault() -> None:
    for name in ("id", "displayName", "legalName", "organisationType", "status", "createdAt"):
        props = _as_stored(tenant_properties(make_tenant(TenantStatus.ACTIVE)))
        del props[name]
        with pytest.raises(TenantRecordInvalid):
            tenant_from_properties(props)


def test_a_status_that_does_not_agree_with_its_times_is_a_record_fault() -> None:
    props = _as_stored(tenant_properties(make_tenant(TenantStatus.ACTIVE)))
    props["status"] = "suspended"  # no suspend time, mode or reason
    with pytest.raises(TenantRecordInvalid):
        tenant_from_properties(props)


def test_the_host_and_the_directory_id_of_a_node_are_not_part_of_the_tenant() -> None:
    props = _as_stored(tenant_properties(make_tenant(TenantStatus.ACTIVE)))
    props["host"] = HOST
    props["entraDirectoryId"] = GUID
    assert tenant_from_properties(props) == make_tenant(TenantStatus.ACTIVE)


# What is sent


async def test_a_key_that_is_not_the_shape_it_names_sends_nothing() -> None:
    connection = RecordingConnection()
    directory = _directory(connection)
    assert await directory.get("platform") is None
    assert await directory.get("net-abcd1234") is None
    assert await directory.get("Not A Tenant") is None
    assert await directory.get(7) is None  # type: ignore[arg-type]
    assert await directory.by_inbound_number("07700 900123", SID) is None
    assert await directory.by_inbound_number(NUMBER, "AC1") is None
    assert await directory.by_inbound_number(None, SID) is None  # type: ignore[arg-type]
    assert await directory.by_account_sid("AC1") is None
    assert await directory.by_host("acme.example.org:8443") is None
    assert await directory.by_host("") is None
    assert await directory.by_entra_directory("common") is None
    assert connection.calls == []


async def test_get_sends_its_statement_with_the_id_and_nothing_else() -> None:
    tenant = make_tenant(TenantStatus.ACTIVE)
    connection = RecordingConnection({"Q-TENANT-GET": [_row(tenant)]})
    assert await _directory(connection).get(tenant.id) == tenant
    assert connection.ids_called() == ["Q-TENANT-GET"]
    assert connection.calls[0][1] == {"id": tenant.id}


async def test_get_answers_none_for_a_tenant_that_is_not_in_the_registry() -> None:
    connection = RecordingConnection({"Q-TENANT-GET": []})
    assert await _directory(connection).get("not-there") is None


async def test_the_number_and_the_account_are_sent_together() -> None:
    tenant = make_tenant(TenantStatus.ACTIVE)
    connection = RecordingConnection({"Q-TENANT-BY-NUMBER": [_line_row(tenant)]})
    line = await _directory(connection).by_inbound_number(NUMBER, SID)
    assert line is not None
    assert line.tenant == tenant
    assert (line.number, line.account_sid) == (NUMBER, SID)
    assert line.secret_ref == "twilio/example-icb/auth-token"
    assert connection.ids_called() == ["Q-TENANT-BY-NUMBER"]
    assert connection.calls[0][1] == {"number": NUMBER, "accountSid": SID}


async def test_no_line_is_found_for_a_number_and_account_nobody_holds() -> None:
    connection = RecordingConnection({"Q-TENANT-BY-NUMBER": []})
    assert await _directory(connection).by_inbound_number(NUMBER, SID) is None


async def test_a_suspended_tenant_is_still_returned_for_the_caller_to_decide() -> None:
    suspended = make_tenant(TenantStatus.SUSPENDED)
    connection = RecordingConnection({"Q-TENANT-BY-NUMBER": [_line_row(suspended)]})
    line = await _directory(connection).by_inbound_number(NUMBER, SID)
    assert line is not None and line.tenant.status is TenantStatus.SUSPENDED


@pytest.mark.parametrize(
    "reference",
    [
        "twilio/other-trust/auth-token",  # another tenant's token
        "link-token",  # a platform secret
        "twilio/example-icb/Auth",
        "",
        None,
        12,
    ],
)
async def test_a_number_whose_secret_is_not_this_tenants_is_a_record_fault(
    reference: Any,
) -> None:
    tenant = make_tenant(TenantStatus.ACTIVE)
    row = _line_row(tenant, ref=reference)
    connection = RecordingConnection({"Q-TENANT-BY-NUMBER": [row], "Q-TENANT-BY-ACCOUNT": [row]})
    with pytest.raises(TenantRecordInvalid) as raised:
        await _directory(connection).by_inbound_number(NUMBER, SID)
    assert "other-trust" not in str(raised.value) and "link-token" not in str(raised.value)
    with pytest.raises(TenantRecordInvalid):
        await _directory(connection).by_account_sid(SID)


async def test_a_row_whose_number_or_account_is_not_the_shape_stored_is_a_record_fault() -> None:
    tenant = make_tenant(TenantStatus.ACTIVE)
    for row in (_line_row(tenant, number="07700 900123"), _line_row(tenant, sid="AC1")):
        connection = RecordingConnection({"Q-TENANT-BY-NUMBER": [row]})
        with pytest.raises(TenantRecordInvalid):
            await _directory(connection).by_inbound_number(NUMBER, SID)


async def test_an_account_with_several_numbers_of_one_tenant_is_that_tenants_line() -> None:
    tenant = make_tenant(TenantStatus.ACTIVE)
    rows = [_line_row(tenant, number=NUMBER), _line_row(tenant, number="+447700900124")]
    connection = RecordingConnection({"Q-TENANT-BY-ACCOUNT": rows})
    line = await _directory(connection).by_account_sid(SID)
    assert line is not None and line.tenant == tenant and line.number == NUMBER
    assert connection.calls[0][1] == {"accountSid": SID}


async def test_an_account_that_two_tenants_hold_is_a_record_fault_and_names_neither() -> None:
    first = make_tenant(TenantStatus.ACTIVE, id="example-icb")
    second = make_tenant(TenantStatus.ACTIVE, id="other-trust")
    rows = [_line_row(first), _line_row(second, number="+447700900124")]
    connection = RecordingConnection({"Q-TENANT-BY-ACCOUNT": rows})
    with pytest.raises(TenantRecordInvalid) as raised:
        await _directory(connection).by_account_sid(SID)
    assert "example-icb" not in str(raised.value) and "other-trust" not in str(raised.value)


async def test_an_account_with_two_secret_references_for_one_tenant_is_a_record_fault() -> None:
    tenant = make_tenant(TenantStatus.ACTIVE)
    rows = [
        _line_row(tenant, number=NUMBER),
        _line_row(tenant, number="+447700900124", ref="twilio/example-icb/auth-token-2"),
    ]
    connection = RecordingConnection({"Q-TENANT-BY-ACCOUNT": rows})
    with pytest.raises(TenantRecordInvalid):
        await _directory(connection).by_account_sid(SID)


async def test_no_line_is_found_for_an_account_nobody_holds() -> None:
    connection = RecordingConnection({"Q-TENANT-BY-ACCOUNT": []})
    assert await _directory(connection).by_account_sid(OTHER_SID) is None


async def test_a_host_is_looked_up_in_lower_case_without_the_final_dot() -> None:
    tenant = make_tenant(TenantStatus.ACTIVE)
    connection = RecordingConnection({"Q-TENANT-BY-HOST": [_row(tenant)]})
    assert await _directory(connection).by_host("Acme.Example.ORG.") == tenant
    assert connection.calls[0][1] == {"host": HOST}


async def test_a_directory_id_is_looked_up_in_lower_case() -> None:
    tenant = make_tenant(TenantStatus.ACTIVE)
    connection = RecordingConnection({"Q-TENANT-BY-ENTRA": [_row(tenant)]})
    assert await _directory(connection).by_entra_directory(GUID.upper()) == tenant
    assert connection.calls[0][1] == {"directoryId": GUID}


async def test_list_active_returns_every_tenant_the_statement_returns_in_order() -> None:
    first = make_tenant(TenantStatus.ACTIVE, id="aa-trust")
    second = make_tenant(TenantStatus.ACTIVE, id="bb-trust")
    connection = RecordingConnection({"Q-TENANT-LIST-ACTIVE": [_row(first), _row(second)]})
    assert await _directory(connection).list_active() == [first, second]
    assert connection.calls[0][1] == {}


async def test_one_bad_record_fails_the_whole_list_rather_than_hiding_a_tenant() -> None:
    good = make_tenant(TenantStatus.ACTIVE, id="aa-trust")
    bad = _row(make_tenant(TenantStatus.ACTIVE, id="bb-trust"))
    bad["tenant"]["status"] = "weird"
    connection = RecordingConnection({"Q-TENANT-LIST-ACTIVE": [_row(good), bad]})
    with pytest.raises(TenantRecordInvalid):
        await _directory(connection).list_active()


async def test_the_ids_of_the_active_tenants_do_not_depend_on_the_rest_of_each_record() -> None:
    """The relay needs ids only, so one tenant with a damaged record cannot stop the others."""
    rows = [{"id": "aa-trust"}, {"id": "bb-trust"}, {"id": None}, {"id": 5}]
    connection = RecordingConnection({"Q-TENANT-ACTIVE-IDS": rows})
    assert list(await _directory(connection).active_tenant_ids()) == ["aa-trust", "bb-trust"]
    assert connection.ids_called() == ["Q-TENANT-ACTIVE-IDS"]


async def test_the_directory_is_global_it_sends_no_tenant_with_or_without_one_bound() -> None:
    tenant = make_tenant(TenantStatus.ACTIVE)
    answers = {
        "Q-TENANT-GET": [_row(tenant)],
        "Q-TENANT-BY-NUMBER": [_line_row(tenant)],
        "Q-TENANT-BY-ACCOUNT": [_line_row(tenant)],
        "Q-TENANT-BY-HOST": [_row(tenant)],
        "Q-TENANT-BY-ENTRA": [_row(tenant)],
        "Q-TENANT-LIST-ACTIVE": [_row(tenant)],
        "Q-TENANT-ACTIVE-IDS": [{"id": tenant.id}],
    }

    async def ask_everything(directory: Neo4jTenantDirectory) -> None:
        await directory.get(tenant.id)
        await directory.by_inbound_number(NUMBER, SID)
        await directory.by_account_sid(SID)
        await directory.by_host(HOST)
        await directory.by_entra_directory(GUID)
        await directory.list_active()
        await directory.active_tenant_ids()

    unbound = RecordingConnection(answers)
    await ask_everything(_directory(unbound))
    bound = RecordingConnection(answers)
    with bind_tenant("other-trust"):
        await ask_everything(_directory(bound))

    assert len(unbound.calls) == 7
    assert unbound.calls == bound.calls
    for _, params in bound.calls:
        assert "tenant" not in params and "parameters" not in params


async def test_nothing_is_logged_for_a_lookup_that_finds_a_tenant_or_faults(
    caplog: pytest.LogCaptureFixture,
) -> None:
    tenant = make_tenant(TenantStatus.ACTIVE)
    good = RecordingConnection({"Q-TENANT-BY-NUMBER": [_line_row(tenant)]})
    bad = RecordingConnection({"Q-TENANT-BY-NUMBER": [_line_row(tenant, ref="link-token")]})
    with caplog.at_level(logging.DEBUG):
        await _directory(good).by_inbound_number(NUMBER, SID)
        with pytest.raises(TenantRecordInvalid):
            await _directory(bad).by_inbound_number(NUMBER, SID)
    assert caplog.records == []


async def test_a_tenant_record_keeps_every_status_the_registry_holds() -> None:
    for status in ALL_STATUSES:
        tenant = replace(make_tenant(status), organisation_type=OrganisationType.OTHER)
        connection = RecordingConnection({"Q-TENANT-GET": [_row(tenant)]})
        assert await _directory(connection).get(tenant.id) == tenant
