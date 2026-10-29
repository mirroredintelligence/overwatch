"""The bus message, its wire form and the one reader of the tenant (TEN-020, DEC-130 item 7).

Every message carries the tenant it belongs to as a property (`tenantId`), the message id and the
session id are qualified with it on the wire (`<tenant>:<local id>`), and one pure function turns a
received message back into a `BusMessage`, refusing a missing, malformed or mismatched tenant with a
fixed reason. The tenant is never in the body. Pure: no SDK, no network. Tenants are made-up.
"""

from collections.abc import Mapping
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from diucs.application.ports.outbound.event_bus import (
    REASON_TENANT_MALFORMED,
    REASON_TENANT_MISMATCH,
    REASON_TENANT_MISSING,
    TENANT_PROPERTY,
    TENANT_REJECTION_REASONS,
    BusMessage,
    MessageTenantError,
    check_publishable,
    from_wire,
    to_wire,
)
from diucs.application.tenancy import ScopeId, bind_scope, bind_tenant
from diucs.domain.errors import DomainError, ValidationFailed

TENANT = "acme-icb"
OTHER = "other-org"


def message(**changes: Any) -> BusMessage:
    fields: dict[str, Any] = {
        "id": "m-1",
        "topic": "capacity.events",
        "event_type": "CapacityReported",
        "session_id": "svc-1",
        "tenant_id": TENANT,
    }
    fields.update(changes)
    return BusMessage(**fields)


def read(
    *,
    message_id: Any = f"{TENANT}:m-1",
    session_id: Any = f"{TENANT}:svc-1",
    subject: Any = "CapacityReported",
    properties: Any = None,
    payload: Any = None,
    topic: str = "capacity.events",
) -> BusMessage:
    return from_wire(
        topic,
        message_id=message_id,
        session_id=session_id,
        subject=subject,
        properties={TENANT_PROPERTY: TENANT} if properties is None else properties,
        payload={} if payload is None else payload,
    )


# ---------------------------------------------------------------- the message (tests 1 and 2)


def test_a_message_with_a_tenant_is_valid() -> None:
    assert message().tenant_id == TENANT


def test_a_message_without_a_tenant_cannot_be_built() -> None:
    with pytest.raises(TypeError):
        BusMessage(  # type: ignore[call-arg]
            id="m-1", topic="capacity.events", event_type="CapacityReported", session_id="svc-1"
        )


@pytest.mark.parametrize(
    "tenant", ["", "Acme", "a:b", "_x", "net-x", "x" * 32, None, b"acme", 7, "a b", "a\n"]
)
def test_a_tenant_that_is_not_a_tenant_id_is_refused(tenant: Any) -> None:
    with pytest.raises(ValidationFailed, match="tenant_id"):
        message(tenant_id=tenant)


def test_an_empty_id_or_an_empty_session_is_refused() -> None:
    with pytest.raises(ValidationFailed, match="id"):
        message(id="")
    with pytest.raises(ValidationFailed, match="session_id"):
        message(session_id="")
    assert message(session_id=None).session_id is None


@pytest.mark.parametrize("key", ["tenantId", "tenant_id", "tenant"])
def test_a_payload_that_names_a_tenant_is_refused(key: str) -> None:
    with pytest.raises(ValidationFailed, match="payload"):
        message(payload={key: TENANT})


@pytest.mark.parametrize("key", ["tenantId", "tenant_id", "tenant"])
def test_a_tenant_nested_inside_the_payload_is_allowed(key: str) -> None:
    assert message(payload={"detail": {key: "x"}}).payload == {"detail": {key: "x"}}


def test_the_payload_is_the_callers_own_dict() -> None:
    payload = {"measure": 4}

    assert message(payload=payload).payload is payload


# ---------------------------------------------------------------- the wire form (tests 3 and 4)


def test_the_wire_form_qualifies_both_ids_and_names_the_tenant() -> None:
    wire = to_wire(message())

    assert wire.message_id == "acme-icb:m-1"
    assert wire.session_id == "acme-icb:svc-1"
    assert wire.subject == "CapacityReported"
    assert dict(wire.application_properties) == {
        "event_type": "CapacityReported",
        "tenantId": TENANT,
    }


def test_a_string_channel_becomes_a_property_and_nothing_else_does() -> None:
    wire = to_wire(message(payload={"channel": "text", "note": "x", "measure": 4}))

    assert dict(wire.application_properties) == {
        "event_type": "CapacityReported",
        "tenantId": TENANT,
        "channel": "text",
    }


def test_a_channel_that_is_not_text_is_ignored_not_stringified() -> None:
    wire = to_wire(message(payload={"channel": 4}))

    assert "channel" not in wire.application_properties


def test_a_message_with_no_session_has_no_wire_session() -> None:
    assert to_wire(message(session_id=None)).session_id is None


def test_a_trace_context_rides_along_as_a_property() -> None:
    trace = "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"

    wire = to_wire(message(traceparent=trace))

    assert wire.application_properties["traceparent"] == trace


def test_the_limit_is_128_characters_on_the_wire_for_the_id() -> None:
    assert len(to_wire(message(id="x" * 119)).message_id) == 128
    with pytest.raises(ValidationFailed, match="id"):
        to_wire(message(id="x" * 120))


def test_the_limit_is_128_characters_on_the_wire_for_the_session() -> None:
    assert len(to_wire(message(session_id="s" * 119)).session_id or "") == 128
    with pytest.raises(ValidationFailed, match="session_id"):
        to_wire(message(session_id="s" * 120))


def test_a_refusal_for_length_never_repeats_the_id() -> None:
    canary = "CANARY" + "x" * 130

    with pytest.raises(ValidationFailed) as refused:
        to_wire(message(id=canary))
    with pytest.raises(ValidationFailed) as refused_session:
        to_wire(message(session_id=canary))

    assert "CANARY" not in str(refused.value)
    assert "CANARY" not in str(refused_session.value)


# ---------------------------------------------------------------- the round trip (test 5)

_ID_TEXT = st.text(alphabet=st.characters(blacklist_categories=("Cs",)), min_size=1, max_size=100)
_TENANT_TEXT = st.from_regex(r"[a-z0-9][a-z0-9-]{1,22}", fullmatch=True).filter(
    lambda text: not text.startswith("net-")
)


def _round_trip(m: BusMessage) -> BusMessage:
    wire = to_wire(m)
    return from_wire(
        m.topic,
        message_id=wire.message_id,
        session_id=wire.session_id,
        subject=wire.subject,
        properties=wire.application_properties,
        payload=m.payload,
    )


@given(tenant=_TENANT_TEXT, local=_ID_TEXT, session=st.none() | _ID_TEXT)
@settings(max_examples=200)
def test_any_valid_message_comes_back_equal(tenant: str, local: str, session: str | None) -> None:
    m = BusMessage(
        id=local,
        topic="capacity.events",
        event_type="CapacityReported",
        payload={"measure": 4},
        session_id=session,
        tenant_id=tenant,
    )

    assert _round_trip(m) == m


@given(tenant=_TENANT_TEXT, local=_ID_TEXT)
def test_the_wire_id_splits_on_its_first_colon_back_into_the_tenant_and_the_local_id(
    tenant: str, local: str
) -> None:
    m = BusMessage(id=local, topic="messages.outbound", event_type="SendMessage", tenant_id=tenant)

    head, _, tail = to_wire(m).message_id.partition(":")

    assert (head, tail) == (tenant, local)


@given(a=_TENANT_TEXT, b=_TENANT_TEXT, local=_ID_TEXT)
def test_the_same_local_id_in_two_tenants_has_two_wire_ids(a: str, b: str, local: str) -> None:
    first = BusMessage(id=local, topic="messages.outbound", event_type="X", tenant_id=a)
    second = BusMessage(id=local, topic="messages.outbound", event_type="X", tenant_id=b)

    assert (to_wire(first).message_id == to_wire(second).message_id) == (a == b)


def test_a_local_id_that_holds_a_colon_does_not_collide_with_another_tenants_id() -> None:
    # `a` with local id `b:c` and `a:b` with local id `c` would both read `a:b:c` if the split
    # were on the last colon; a tenant id holds no colon, so the first colon is the only split.
    first = BusMessage(id="y:z", topic="messages.outbound", event_type="X", tenant_id="x")
    second = BusMessage(id="z", topic="messages.outbound", event_type="X", tenant_id="x")

    assert to_wire(first).message_id == "x:y:z"
    assert to_wire(second).message_id == "x:z"
    assert _round_trip(first).id == "y:z"


# ---------------------------------------------------------------- the reader (tests 6 to 8)


@pytest.mark.parametrize(
    "properties",
    [
        pytest.param({}, id="empty-properties"),
        pytest.param({"tenantId": None}, id="null"),
        pytest.param({"tenantId": ""}, id="empty-text"),
        pytest.param({"tenantId": b""}, id="empty-bytes"),
        pytest.param({"event_type": "X"}, id="other-properties-only"),
    ],
)
def test_a_missing_tenant_is_tenant_missing(properties: Any) -> None:
    with pytest.raises(MessageTenantError) as refused:
        read(properties=properties)

    assert refused.value.reason == REASON_TENANT_MISSING


def test_no_property_mapping_at_all_is_tenant_missing() -> None:
    with pytest.raises(MessageTenantError) as refused:
        from_wire(
            "capacity.events",
            message_id=f"{TENANT}:m-1",
            session_id=None,
            subject="X",
            properties=None,
            payload={},
        )

    assert refused.value.reason == REASON_TENANT_MISSING


@pytest.mark.parametrize(
    "properties",
    [
        pytest.param({"tenantId": 7}, id="an-int"),
        pytest.param({"tenantId": True}, id="a-bool"),
        pytest.param({"tenantId": b"\xff"}, id="bytes-not-utf-8"),
        pytest.param({"tenantId": "Acme"}, id="upper-case"),
        pytest.param({"tenantId": "a:b"}, id="a-colon"),
        pytest.param({"tenantId": "x" * 40}, id="too-long"),
        pytest.param({"tenantId": "net-x"}, id="a-network-id"),
        pytest.param({"tenantId": "_x"}, id="underscore"),
        pytest.param({"tenantId": f"{TENANT} "}, id="trailing-space"),
        pytest.param({"tenantId": TENANT, b"tenantId": TENANT.encode()}, id="both-key-forms"),
    ],
)
def test_a_malformed_tenant_is_tenant_malformed(properties: Any) -> None:
    with pytest.raises(MessageTenantError) as refused:
        read(properties=properties)

    assert refused.value.reason == REASON_TENANT_MALFORMED


@pytest.mark.parametrize(
    ("message_id", "session_id"),
    [
        pytest.param("other-org:m-1", f"{TENANT}:svc-1", id="id-prefix-is-another-tenant"),
        pytest.param("m-1", f"{TENANT}:svc-1", id="id-has-no-colon"),
        pytest.param("", f"{TENANT}:svc-1", id="id-empty"),
        pytest.param(None, f"{TENANT}:svc-1", id="id-missing"),
        pytest.param(f"{TENANT}:m-1", "other-org:svc-1", id="session-prefix-is-another-tenant"),
        pytest.param(f"{TENANT}:m-1", "svc-1", id="session-has-no-colon"),
        pytest.param(f"{TENANT}:m-1", f"{TENANT}:", id="session-local-part-is-empty"),
        pytest.param(f"{TENANT}:m-1", TENANT, id="session-is-just-the-tenant"),
    ],
)
def test_ids_that_do_not_belong_to_the_tenant_are_tenant_mismatch(
    message_id: Any, session_id: Any
) -> None:
    with pytest.raises(MessageTenantError) as refused:
        read(message_id=message_id, session_id=session_id)

    assert refused.value.reason == REASON_TENANT_MISMATCH


def test_a_prefix_that_only_starts_like_the_tenant_is_a_mismatch() -> None:
    # `acme-icb2:m-1` starts with the tenant text but its first-colon prefix is another tenant.
    with pytest.raises(MessageTenantError) as refused:
        read(message_id=f"{TENANT}2:m-1")

    assert refused.value.reason == REASON_TENANT_MISMATCH


def test_no_session_on_the_wire_is_no_session() -> None:
    assert read(session_id=None).session_id is None
    assert read(session_id="").session_id is None


def test_bytes_keys_and_values_are_read_as_text() -> None:
    result = read(
        properties={b"tenantId": TENANT.encode(), b"event_type": b"CapacityReported"},
        subject=None,
    )

    assert result.tenant_id == TENANT
    assert result.event_type == "CapacityReported"


def test_a_bytes_key_that_is_not_text_is_ignored_not_fatal() -> None:
    result = read(properties={"tenantId": TENANT, b"\xff": b"x"})

    assert result.tenant_id == TENANT


def test_the_local_ids_come_back_without_the_tenant() -> None:
    result = read(message_id="acme-icb:w:1", session_id="acme-icb:svc:9")

    assert (result.id, result.session_id) == ("w:1", "svc:9")


def test_the_event_type_is_the_subject_then_the_property() -> None:
    assert read(
        subject="FromSubject", properties={"tenantId": TENANT, "event_type": "P"}
    ).event_type == ("FromSubject")
    assert read(
        subject="", properties={"tenantId": TENANT, "event_type": "FromProperty"}
    ).event_type == ("FromProperty")


def test_a_message_with_no_event_type_is_refused() -> None:
    with pytest.raises(ValidationFailed, match="event_type"):
        read(subject=None, properties={"tenantId": TENANT})


def test_a_payload_that_is_not_an_object_is_refused() -> None:
    with pytest.raises(ValidationFailed, match="payload"):
        read(payload=[1, 2])


def test_the_topic_and_payload_pass_through() -> None:
    result = read(topic="booking.events", payload={"a": 1})

    assert result.topic == "booking.events"
    assert result.payload == {"a": 1}


def test_a_refusal_never_repeats_what_it_was_given() -> None:
    canary = "CANARY-Tenant-123"

    with pytest.raises(MessageTenantError) as refused:
        read(properties={"tenantId": canary})
    with pytest.raises(MessageTenantError) as mismatch:
        read(message_id=f"{canary}:m-1")

    assert "CANARY" not in str(refused.value)
    assert "CANARY" not in str(mismatch.value)


def test_the_error_is_a_domain_error_whose_message_is_its_reason() -> None:
    error = MessageTenantError(REASON_TENANT_MISSING)

    assert isinstance(error, DomainError)
    assert str(error) == REASON_TENANT_MISSING
    assert error.reason == REASON_TENANT_MISSING
    assert TENANT_REJECTION_REASONS == ("tenant-missing", "tenant-malformed", "tenant-mismatch")
    assert TENANT_PROPERTY == "tenantId"


_ANY_VALUE = st.one_of(
    st.none(), st.booleans(), st.integers(), st.text(max_size=20), st.binary(max_size=20)
)


@given(
    message_id=_ANY_VALUE,
    session_id=_ANY_VALUE,
    properties=st.none()
    | st.dictionaries(st.text(max_size=12) | st.binary(max_size=12), _ANY_VALUE),
)
@settings(max_examples=300)
def test_the_reader_raises_only_its_two_errors_whatever_it_is_given(
    message_id: Any, session_id: Any, properties: Mapping[str | bytes, object] | None
) -> None:
    try:
        from_wire(
            "capacity.events",
            message_id=message_id,
            session_id=session_id,
            subject="X",
            properties=properties,
            payload={},
        )
    except MessageTenantError as error:
        assert error.reason in TENANT_REJECTION_REASONS
        assert str(error) == error.reason
    except ValidationFailed:
        pass


# ---------------------------------------------------------------- publishing (test 9)


def test_with_nothing_bound_the_message_declares_its_own_tenant() -> None:
    check_publishable(message())


def test_a_bound_tenant_that_matches_passes() -> None:
    with bind_tenant(TENANT):
        check_publishable(message())


def test_a_bound_tenant_that_differs_is_refused() -> None:
    with bind_tenant(OTHER), pytest.raises(ValidationFailed, match="tenant_id"):
        check_publishable(message())


def test_a_bound_network_scope_is_refused() -> None:
    with (
        bind_scope(ScopeId.network("net-region")),
        pytest.raises(ValidationFailed, match="tenant_id"),
    ):
        check_publishable(message())


@pytest.mark.parametrize("key", ["link", "link_token", "token", "url"])
def test_a_payload_that_carries_a_live_link_is_refused(key: str) -> None:
    with pytest.raises(ValidationFailed, match="payload"):
        check_publishable(message(payload={key: "https://example.test/x"}))


@pytest.mark.parametrize(
    "payload", [{"links": 1}, {"detail": {"link": "x"}}, {"sealed_content": "x"}]
)
def test_a_key_that_only_looks_like_one_is_allowed(payload: dict[str, Any]) -> None:
    check_publishable(message(payload=payload))


def test_the_refusals_are_fixed_words_with_no_value() -> None:
    with bind_tenant(OTHER), pytest.raises(ValidationFailed) as mismatch:
        check_publishable(message(payload={"note": "CANARY"}))
    with pytest.raises(ValidationFailed) as link:
        check_publishable(message(payload={"token": "CANARY-token-123"}))

    assert OTHER not in str(mismatch.value) and TENANT not in str(mismatch.value)
    assert "CANARY" not in str(link.value)
