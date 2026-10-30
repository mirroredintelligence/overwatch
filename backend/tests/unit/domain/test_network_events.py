"""Tests for the network domain events and the projection message (TEN-038, DEC-132, DEC-134).

Eleven event classes, the `network.events` topic, and one bounded exception to the rule that an
event carries only identifiers, counts and codes: `ProjectionRequested`, whose body holds the
allowlisted projection fields. The generic D25 tests in test_events.py also run over the eleven
samples. Synthetic values only: invented organisations (`tenant-a`, `net-test`) and `UCR West`.
"""

import dataclasses
import json
import math
import types
import typing
from datetime import UTC, datetime, timedelta, timezone
from enum import Enum
from typing import Any, get_args, get_type_hints

import pytest

from diucs.application.ports.outbound.event_bus import QUEUES, TOPICS
from diucs.domain import events
from diucs.domain.errors import ValidationFailed
from diucs.domain.events import (
    NETWORK_EVENTS,
    PAYLOAD_EXCEPTIONS,
    PROJECTION_WORK,
    AgreementRecorded,
    DomainEvent,
    GrantApproved,
    GrantEffective,
    GrantEnded,
    GrantProposed,
    MemberAdded,
    MemberRemoved,
    NetworkCreated,
    ProjectionApplied,
    ProjectionRejected,
    ProjectionRejectReason,
    ProjectionRequested,
    ServiceDirectoryChanged,
    from_payload,
    session_id_for,
    topic_for,
)
from diucs.domain.model.network import (
    DirectorySource,
    GrantApprover,
    GrantEndReason,
    GrantScope,
    GrantStatus,
    MembershipEndReason,
)

AT = datetime(2026, 10, 23, 10, 12, tzinfo=UTC)
EFFECTIVE = datetime(2026, 11, 1, 0, 0, tzinfo=UTC)
MICROS = datetime(2026, 10, 23, 10, 12, 30, 500000, tzinfo=UTC)
BST = timezone(timedelta(hours=1))
AT_TEXT = "2026-10-23T10:12:00Z"

NETWORK_CLASSES = (
    NetworkCreated,
    MemberAdded,
    MemberRemoved,
    AgreementRecorded,
    GrantProposed,
    GrantApproved,
    GrantEffective,
    GrantEnded,
    ProjectionApplied,
    ProjectionRejected,
)
ELEVEN = (*NETWORK_CLASSES, ServiceDirectoryChanged)
IDENTITY = ("grant-1", "net-test", "tenant-b", GrantScope.CAPACITY, 1)


def samples() -> tuple[Any, ...]:
    return (
        NetworkCreated("net-test", "tenant-a", AT),
        MemberAdded("net-test", "tenant-b", AT),
        MemberRemoved("net-test", "tenant-b", MembershipEndReason.REMOVED, AT),
        AgreementRecorded("net-test", "DSA-2026/14", 2, AT),
        GrantProposed(*IDENTITY, AT),
        GrantApproved(*IDENTITY, GrantApprover.GRANTOR, AT),
        GrantEffective(*IDENTITY, EFFECTIVE, AT),
        GrantEnded(*IDENTITY, GrantEndReason.LAPSED, AT),
        ProjectionApplied("net-test", "tenant-b", GrantScope.CAPACITY, "svc-ucr-west", 3, AT),
        ProjectionRejected(
            "net-test", "tenant-b", GrantScope.DIRECTORY, ProjectionRejectReason.INVALID_BODY, AT
        ),
        ServiceDirectoryChanged("svc-ucr-west", DirectorySource.MANUAL, AT),
    )


# 1. exact payloads


def test_each_payload_has_the_documented_keys_in_order() -> None:
    expected = {
        "NetworkCreated": {"network_id": "net-test", "owner_tenant_id": "tenant-a", "at": AT_TEXT},
        "MemberAdded": {"network_id": "net-test", "member_tenant_id": "tenant-b", "at": AT_TEXT},
        "MemberRemoved": {
            "network_id": "net-test",
            "member_tenant_id": "tenant-b",
            "reason": "removed",
            "at": AT_TEXT,
        },
        "AgreementRecorded": {
            "network_id": "net-test",
            "reference": "DSA-2026/14",
            "version": 2,
            "at": AT_TEXT,
        },
        "GrantProposed": {
            "grant_id": "grant-1",
            "network_id": "net-test",
            "grantor_tenant_id": "tenant-b",
            "scope": "capacity",
            "version": 1,
            "at": AT_TEXT,
        },
        "GrantApproved": {
            "grant_id": "grant-1",
            "network_id": "net-test",
            "grantor_tenant_id": "tenant-b",
            "scope": "capacity",
            "version": 1,
            "by": "grantor",
            "at": AT_TEXT,
        },
        "GrantEffective": {
            "grant_id": "grant-1",
            "network_id": "net-test",
            "grantor_tenant_id": "tenant-b",
            "scope": "capacity",
            "version": 1,
            "effective_from": "2026-11-01T00:00:00Z",
            "at": AT_TEXT,
        },
        "GrantEnded": {
            "grant_id": "grant-1",
            "network_id": "net-test",
            "grantor_tenant_id": "tenant-b",
            "scope": "capacity",
            "version": 1,
            "reason": "lapsed",
            "at": AT_TEXT,
        },
        "ProjectionApplied": {
            "network_id": "net-test",
            "source_tenant_id": "tenant-b",
            "kind": "capacity",
            "item_id": "svc-ucr-west",
            "source_version": 3,
            "at": AT_TEXT,
        },
        "ProjectionRejected": {
            "network_id": "net-test",
            "source_tenant_id": "tenant-b",
            "kind": "directory",
            "reason": "invalid-body",
            "at": AT_TEXT,
        },
        "ServiceDirectoryChanged": {
            "service_id": "svc-ucr-west",
            "source": "manual",
            "at": AT_TEXT,
        },
    }
    for event in samples():
        payload = event.to_payload()
        assert payload == expected[event.event_type], event.event_type
        assert list(payload) == list(expected[event.event_type]), event.event_type


# 2. topics and sessions


def test_the_ten_network_events_go_to_network_events_and_the_directory_change_to_registration() -> (
    None
):
    assert NETWORK_EVENTS == "network.events"
    for event in samples():
        if isinstance(event, ServiceDirectoryChanged):
            assert topic_for(event) == "registration.events"
        else:
            assert topic_for(event) == "network.events"


def test_none_of_the_eleven_has_a_session() -> None:
    for event in samples():
        assert session_id_for(event) is None


def test_the_eleven_are_in_the_union() -> None:
    assert set(ELEVEN) <= set(get_args(DomainEvent))


# 3. round trips


def test_every_sample_round_trips_and_is_json_safe() -> None:
    for event in samples():
        payload = event.to_payload()
        assert json.loads(json.dumps(payload)) == payload
        assert from_payload(event.event_type, payload) == event


def test_microseconds_are_kept_in_at_and_in_effective_from() -> None:
    event = GrantEffective(*IDENTITY, MICROS, MICROS)
    payload = event.to_payload()
    assert payload["effective_from"] == "2026-10-23T10:12:30.500000Z"
    assert payload["at"] == "2026-10-23T10:12:30.500000Z"
    assert from_payload("GrantEffective", payload) == event


def test_the_event_type_is_the_class_name() -> None:
    for event in samples():
        assert event.event_type == type(event).__name__


# 4. enum identity (lesson L3)


@pytest.mark.parametrize(
    ("build", "field"),
    [
        (lambda v: GrantEnded(*IDENTITY, v, AT), "reason"),
        (lambda v: MemberRemoved("net-test", "tenant-b", v, AT), "reason"),
        (lambda v: GrantApproved(*IDENTITY, v, AT), "by"),
        (lambda v: ProjectionApplied("net-test", "tenant-b", v, "svc-1", 1, AT), "kind"),
        (
            lambda v: ProjectionRejected("net-test", "tenant-b", GrantScope.CAPACITY, v, AT),
            "reason",
        ),
        (lambda v: ServiceDirectoryChanged("svc-1", v, AT), "source"),
        (lambda v: GrantProposed("grant-1", "net-test", "tenant-b", v, 1, AT), "scope"),
    ],
)
@pytest.mark.parametrize("wrong", [GrantStatus.ENDED, "capacity", "ended", "left", None, 1])
def test_a_wrong_enum_is_refused_by_exact_type(build: Any, field: str, wrong: object) -> None:
    # No value here is an instance of any field's own enum, though some compare equal to a member
    # of one (lesson L3), so only an identity check refuses them.
    with pytest.raises(ValidationFailed) as info:
        build(wrong)
    assert info.value.field == field
    if isinstance(wrong, str):
        assert wrong not in str(info.value)


def test_a_grant_ended_reason_from_grant_status_is_refused_though_it_compares_equal() -> None:
    assert GrantEndReason.ENDED == GrantStatus.ENDED
    with pytest.raises(ValidationFailed) as info:
        GrantEnded(*IDENTITY, GrantStatus.ENDED, AT)  # type: ignore[arg-type]
    assert info.value.field == "reason"


def test_a_decoded_reason_must_be_the_fields_own_enum_and_is_not_echoed() -> None:
    payload = MemberRemoved("net-test", "tenant-b", MembershipEndReason.LEFT, AT).to_payload()
    assert from_payload("MemberRemoved", payload).reason is MembershipEndReason.LEFT  # type: ignore[union-attr]
    payload["reason"] = "ended"
    with pytest.raises(ValidationFailed) as info:
        from_payload("MemberRemoved", payload)
    assert info.value.field == "reason"
    assert "ended" not in str(info.value)


# 5. id kinds and values


def test_a_tenant_id_in_a_network_field_and_a_network_id_in_a_tenant_field_are_refused() -> None:
    with pytest.raises(ValidationFailed) as network:
        NetworkCreated("tenant-a", "tenant-a", AT)
    assert network.value.field == "network_id"
    with pytest.raises(ValidationFailed) as owner:
        NetworkCreated("net-test", "net-other", AT)
    assert owner.value.field == "owner_tenant_id"
    with pytest.raises(ValidationFailed) as member:
        MemberAdded("net-test", "net-other", AT)
    assert member.value.field == "member_tenant_id"
    with pytest.raises(ValidationFailed) as source:
        ProjectionApplied("net-test", "net-other", GrantScope.CAPACITY, "svc-1", 1, AT)
    assert source.value.field == "source_tenant_id"
    with pytest.raises(ValidationFailed) as grantor:
        GrantProposed("grant-1", "net-test", "net-other", GrantScope.CAPACITY, 1, AT)
    assert grantor.value.field == "grantor_tenant_id"


@pytest.mark.parametrize("version", [0, -1, True, "1", 1.0, None])
def test_a_version_is_a_whole_number_of_at_least_one(version: object) -> None:
    with pytest.raises(ValidationFailed) as info:
        GrantProposed("grant-1", "net-test", "tenant-b", GrantScope.CAPACITY, version, AT)  # type: ignore[arg-type]
    assert info.value.field == "version"
    with pytest.raises(ValidationFailed) as other:
        ProjectionApplied("net-test", "tenant-b", GrantScope.CAPACITY, "svc-1", version, AT)  # type: ignore[arg-type]
    assert other.value.field == "source_version"
    with pytest.raises(ValidationFailed) as agreement:
        AgreementRecorded("net-test", "DSA-2026/14", version, AT)  # type: ignore[arg-type]
    assert agreement.value.field == "version"


@pytest.mark.parametrize(
    "bad", ["Jane Smith", "DT4 8XX", "", "a" * 65, "-lead", "a b", "a_b", 7, None]
)
def test_a_grant_item_or_service_id_matches_the_id_pattern(bad: object) -> None:
    with pytest.raises(ValidationFailed) as grant:
        GrantProposed(bad, "net-test", "tenant-b", GrantScope.CAPACITY, 1, AT)  # type: ignore[arg-type]
    assert grant.value.field == "grant_id"
    with pytest.raises(ValidationFailed) as item:
        ProjectionApplied("net-test", "tenant-b", GrantScope.CAPACITY, bad, 1, AT)  # type: ignore[arg-type]
    assert item.value.field == "item_id"
    with pytest.raises(ValidationFailed) as service:
        ServiceDirectoryChanged(bad, DirectorySource.MANUAL, AT)  # type: ignore[arg-type]
    assert service.value.field == "service_id"
    assert not isinstance(bad, str) or bad == "" or bad not in str(grant.value)


@pytest.mark.parametrize("ok", ["a", "svc-ucr-west", "A1", "a" * 64])
def test_ids_at_the_pattern_edges_are_accepted(ok: str) -> None:
    assert ServiceDirectoryChanged(ok, DirectorySource.MANUAL, AT).service_id == ok


@pytest.mark.parametrize(
    "reference", ["943 476 5919", "DT4 8XX", "", "a b", "Jane Smith", 4821, None]
)
def test_an_agreement_reference_is_a_short_reference_with_no_patient_shape(
    reference: object,
) -> None:
    with pytest.raises(ValidationFailed) as info:
        AgreementRecorded("net-test", reference, 1, AT)  # type: ignore[arg-type]
    assert info.value.field == "reference"


def test_an_agreement_reference_with_the_documented_shape_builds() -> None:
    assert AgreementRecorded("net-test", "DSA-2026/14", 1, AT).reference == "DSA-2026/14"


@pytest.mark.parametrize("reference", ["9434765919", "AB1 2CD"])
def test_a_reference_that_is_a_nhs_number_or_postcode_shape_is_refused(reference: str) -> None:
    with pytest.raises(ValidationFailed):
        AgreementRecorded("net-test", reference, 1, AT)


# 6. timestamps


@pytest.mark.parametrize("cls", ELEVEN)
def test_a_naive_or_non_utc_at_is_refused(cls: type) -> None:
    template = next(e for e in samples() if type(e) is cls)
    for bad in (datetime(2026, 10, 23, 10, 12), datetime(2026, 10, 23, 11, 12, tzinfo=BST)):
        with pytest.raises(ValidationFailed) as info:
            dataclasses.replace(template, at=bad)
        assert info.value.field == "at"


def test_a_naive_or_non_utc_effective_from_is_refused() -> None:
    for bad in (datetime(2026, 11, 1), datetime(2026, 11, 1, 1, 0, tzinfo=BST)):
        with pytest.raises(ValidationFailed) as info:
            GrantEffective(*IDENTITY, bad, AT)
        assert info.value.field == "effective_from"


@pytest.mark.parametrize("cls", ELEVEN)
def test_decode_needs_every_key_and_names_the_missing_one(cls: type) -> None:
    template = next(e for e in samples() if type(e) is cls)
    for key in template.to_payload():
        payload = template.to_payload()
        del payload[key]
        with pytest.raises(ValidationFailed) as info:
            from_payload(cls.__name__, payload)
        assert info.value.field == key


@pytest.mark.parametrize(
    "bad", ["2026-10-23T11:12:00+01:00", "2026-10-23T10:12:00", "yesterday", 5]
)
@pytest.mark.parametrize("cls", ELEVEN)
def test_decode_refuses_an_at_that_is_not_utc_text(cls: type, bad: object) -> None:
    payload = next(e for e in samples() if type(e) is cls).to_payload()
    payload["at"] = bad
    with pytest.raises(ValidationFailed) as info:
        from_payload(cls.__name__, payload)
    assert info.value.field == "at"


def test_decode_refuses_an_effective_from_with_an_offset() -> None:
    payload = GrantEffective(*IDENTITY, EFFECTIVE, AT).to_payload()
    payload["effective_from"] = "2026-11-01T01:00:00+01:00"
    with pytest.raises(ValidationFailed) as info:
        from_payload("GrantEffective", payload)
    assert info.value.field == "effective_from"


# 7. no patient field


def test_no_network_event_has_a_patient_or_free_text_field() -> None:
    forbidden = {
        "postcode",
        "name",
        "nhs_number",
        "needs",
        "phone",
        "email",
        "comment",
        "free_text",
        "address",
        "note",
        "text",
        "display_name",
        "body",
    }
    for cls in ELEVEN:
        names = {field.name for field in dataclasses.fields(cls)}
        assert names.isdisjoint(forbidden), cls.__name__


# 8. reject reasons


def test_the_reject_reasons_are_exactly_these_five() -> None:
    assert {reason.value for reason in ProjectionRejectReason} == {
        "grant-not-effective",
        "member-not-active",
        "listing-not-admitted",
        "allowlist-mismatch",
        "invalid-body",
    }
    with pytest.raises(ValidationFailed):
        ProjectionRejected("net-test", "tenant-b", GrantScope.CAPACITY, "invalid-body", AT)  # type: ignore[arg-type]


# 9. the exception is bounded


def test_the_only_payload_exception_is_the_projection_message() -> None:
    assert frozenset({"ProjectionRequested"}) == PAYLOAD_EXCEPTIONS


def _module_dataclasses() -> list[type]:
    return [
        value
        for value in vars(events).values()
        if isinstance(value, type)
        and dataclasses.is_dataclass(value)
        and value.__module__ == events.__name__
    ]


def _plain_kinds(annotation: object) -> set[object]:
    if typing.get_origin(annotation) in (typing.Union, types.UnionType):
        return {kind for part in get_args(annotation) for kind in _plain_kinds(part)}
    return {annotation}


def test_every_field_of_every_class_is_a_time_a_count_a_code_or_an_id() -> None:
    classes = _module_dataclasses()
    assert len(classes) >= 30
    for cls in classes:
        hints = get_type_hints(cls)
        for field in dataclasses.fields(cls):
            if cls.__name__ in PAYLOAD_EXCEPTIONS and field.name == "body":
                continue
            kinds = _plain_kinds(hints[field.name]) - {type(None)}
            for kind in kinds:
                ok = kind in (datetime, int) or (isinstance(kind, type) and issubclass(kind, Enum))
                ok = ok or (
                    kind is str and (field.name.endswith("_id") or field.name == "reference")
                )
                assert ok, f"{cls.__name__}.{field.name}: {kind}"


def test_only_the_projection_message_has_a_mapping_field_and_it_is_the_body() -> None:
    from collections.abc import Mapping

    for cls in _module_dataclasses():
        for field in dataclasses.fields(cls):
            hint = get_type_hints(cls)[field.name]
            if typing.get_origin(hint) is Mapping or hint is Mapping:
                assert cls.__name__ in PAYLOAD_EXCEPTIONS
                assert field.name == "body"


def test_the_projection_message_is_not_an_event() -> None:
    assert ProjectionRequested not in get_args(DomainEvent)
    with pytest.raises(ValidationFailed):
        from_payload("ProjectionRequested", {})
    assert not hasattr(ProjectionRequested, "event_type")


def test_the_module_says_what_the_exception_is() -> None:
    doc = events.__doc__ or ""
    assert "ProjectionRequested" in doc
    assert "allowlist" in doc


# 12. the topic and the queue name


def test_the_network_topic_is_registered_and_the_projection_queue_is_not_yet() -> None:
    assert "network.events" in TOPICS
    assert PROJECTION_WORK == "projection.work"
    assert PROJECTION_WORK not in QUEUES


# ProjectionRequested


def message(**changes: Any) -> ProjectionRequested:
    fields: dict[str, Any] = {
        "network_id": "net-test",
        "source_tenant_id": "tenant-b",
        "grant_id": "grant-1",
        "grant_version": 1,
        "kind": GrantScope.CAPACITY,
        "source_service_id": "svc-ucr-west",
        "source_version": 4,
        "allowlist_version": 1,
        "body": {
            "service_name": "UCR West",
            "value": 4,
            "suspended": False,
            "opening_hours": ("0 08:00:00 18:00:00", "1 all-day"),
            "reported_at": "2026-10-23T10:12:00Z",
            "ratio": 0.5,
            "missing": None,
        },
        "at": AT,
    }
    fields.update(changes)
    return ProjectionRequested(**fields)


def test_a_projection_message_round_trips_with_tuples_kept_as_tuples() -> None:
    original = message()
    payload = original.to_payload()
    assert json.loads(json.dumps(payload)) == payload
    assert isinstance(payload["body"]["opening_hours"], list)
    rebuilt = ProjectionRequested.decode(json.loads(json.dumps(payload)))
    assert rebuilt == original
    assert isinstance(rebuilt.body["opening_hours"], tuple)


def test_the_payload_has_the_shape_of_the_events_with_the_body_as_an_object() -> None:
    payload = message(body={}).to_payload()
    assert list(payload) == [
        "network_id",
        "source_tenant_id",
        "grant_id",
        "grant_version",
        "kind",
        "source_service_id",
        "source_version",
        "allowlist_version",
        "body",
        "at",
    ]
    assert payload["kind"] == "capacity"
    assert payload["body"] == {}
    assert payload["at"] == AT_TEXT
    assert message().message_type == "ProjectionRequested"


def test_an_empty_body_is_valid() -> None:
    assert message(body={}).body == {}


def test_the_body_cannot_be_changed_after_the_message_is_built() -> None:
    source = {"value": 1}
    built = message(body=source)
    source["value"] = 2
    assert built.body["value"] == 1
    with pytest.raises(TypeError):
        built.body["value"] = 3  # type: ignore[index]


@pytest.mark.parametrize(
    "key",
    [
        "postcode",
        "patient_name",
        "patientName",
        "NHS_number",
        "nhsNumber",
        "address",
        "dob",
        "free_text",
        "free-text",
        "name",
        "phone",
        "tenant_id",
        "Value",
        "1value",
        "",
        "a" * 41,
        "a b",
    ],
)
def test_a_forbidden_or_malformed_key_is_refused(key: str) -> None:
    with pytest.raises(ValidationFailed) as info:
        message(body={key: "x"})
    assert info.value.field == "body"


def test_a_non_text_key_is_refused() -> None:
    with pytest.raises(ValidationFailed):
        message(body={1: "x"})  # type: ignore[dict-item]


def test_forty_keys_are_allowed_and_forty_one_are_not() -> None:
    assert len(message(body={f"k{n}": n for n in range(40)}).body) == 40
    with pytest.raises(ValidationFailed):
        message(body={f"k{n}": n for n in range(41)})


@pytest.mark.parametrize(
    "value",
    [
        {"a": 1},
        [[1]],
        ((1,),),
        datetime(2026, 10, 23, tzinfo=UTC),
        b"bytes",
        {1, 2},
        float("nan"),
        float("inf"),
        "DT4 8XX",
        "Seen by Mrs Smith",
        "943 476 5919",
        "a" * 201,
        ("ok", "DT4 8XX"),
        ("a",) * 51,
        (("a",),),
        (None,),
    ],
)
def test_a_value_that_is_not_a_flat_scalar_or_has_a_patient_shape_is_refused(value: object) -> None:
    with pytest.raises(ValidationFailed) as info:
        message(body={"value": value})
    assert info.value.field == "body"


def test_scalar_edges_are_accepted() -> None:
    body = {
        "a": "x" * 200,
        "b": ("t",) * 50,
        "c": True,
        "d": 0,
        "e": -1.5,
        "f": None,
        "g": ("a", 1, 2.5, False),
    }
    assert message(body=body).body["a"] == "x" * 200
    assert math.isfinite(message(body=body).body["e"])  # type: ignore[arg-type]


def test_a_list_in_the_body_is_accepted_as_a_tuple_when_decoded_and_refused_when_built() -> None:
    payload = message().to_payload()
    payload["body"]["opening_hours"] = ["0 08:00:00 18:00:00"]
    assert isinstance(ProjectionRequested.decode(payload).body["opening_hours"], tuple)
    with pytest.raises(ValidationFailed):
        message(body={"opening_hours": ["0 08:00:00 18:00:00"]})  # type: ignore[dict-item]


def test_decode_refuses_a_nested_list() -> None:
    payload = message().to_payload()
    payload["body"]["opening_hours"] = [["a"]]
    with pytest.raises(ValidationFailed):
        ProjectionRequested.decode(payload)


def test_the_envelope_fields_are_checked_like_the_event_fields() -> None:
    for changes, field in (
        ({"source_tenant_id": "net-x"}, "source_tenant_id"),
        ({"network_id": "tenant-a"}, "network_id"),
        ({"grant_id": "Jane Smith"}, "grant_id"),
        ({"source_service_id": "DT4 8XX"}, "source_service_id"),
        ({"grant_version": 0}, "grant_version"),
        ({"source_version": True}, "source_version"),
        ({"allowlist_version": 0}, "allowlist_version"),
        ({"kind": GrantStatus.ENDED}, "kind"),
        ({"kind": "capacity"}, "kind"),
        ({"at": datetime(2026, 10, 23)}, "at"),
    ):
        with pytest.raises(ValidationFailed) as info:
            message(**changes)
        assert info.value.field == field, changes


def test_decode_needs_every_key() -> None:
    for key in message().to_payload():
        payload = message().to_payload()
        del payload[key]
        with pytest.raises(ValidationFailed) as info:
            ProjectionRequested.decode(payload)
        assert info.value.field == key


def test_decode_refuses_a_body_that_is_not_an_object() -> None:
    payload = message().to_payload()
    payload["body"] = ["a"]
    with pytest.raises(ValidationFailed) as info:
        ProjectionRequested.decode(payload)
    assert info.value.field == "body"


def test_the_payload_uses_none_of_the_keys_the_bus_refuses() -> None:
    for key in ("link", "link_token", "token", "url"):
        assert key not in message().to_payload()
        for event in samples():
            assert key not in event.to_payload()


def test_a_refusal_never_echoes_the_value() -> None:
    with pytest.raises(ValidationFailed) as info:
        message(body={"value": "Seen by Mrs Smith"})
    assert "Smith" not in str(info.value)
    with pytest.raises(ValidationFailed) as other:
        message(body={"patient_name": "x"})
    assert "patient_name" not in str(other.value)
