"""The tenant's own Organization from its ODS record (DEC-1314): the bundle, and that the mapper
maps every element of it (nothing is dropped, nothing unmapped is written)."""

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from overwatch.adapters.outbound.graph_store.bundle_writer import resolve_bundle
from overwatch.adapters.outbound.graph_store.mapper import ODS_ORG_SYSTEM, from_graph, to_graph
from overwatch.application.ods_organisation import organisation_bundle, organisation_resource
from overwatch.domain.codes import BASE_URL
from overwatch.domain.model.ods_record import OdsLink, OdsOrganisationRecord, OdsRole

NOW = datetime(2026, 10, 31, 9, 30, tzinfo=UTC)
RECORD = OdsOrganisationRecord(
    code="F81044",
    name="THE ARDLEIGH SURGERY",
    status="Active",
    postcode="CO7 7LD",
    primary_role="RO177",
    roles=(
        OdsRole("RO177", "PRESCRIBING COST CENTRE", True),
        OdsRole("RO76", "GP PRACTICE", False),
    ),
    links=(OdsLink("RE4", "F81045", "A PARENT PRACTICE", "RO98"),),
    last_changed_at="2024-05-01",
)


def _ext(resource: dict[str, Any], short_name: str) -> Any:
    (entry,) = [
        e
        for e in resource["extension"]
        if e["url"] == f"{BASE_URL}StructureDefinition/{short_name}"
    ]
    return next(v for k, v in entry.items() if k != "url")


def test_a_record_becomes_an_organization_with_its_code_name_status_postcode_and_roles() -> None:
    resource = organisation_resource(
        ods_code="F81044", legal_name="Ardleigh Ltd", record=RECORD, now=NOW
    )

    assert resource["resourceType"] == "Organization" and resource["id"] == "F81044"
    assert resource["identifier"] == [{"system": ODS_ORG_SYSTEM, "value": "F81044"}]
    assert resource["name"] == "THE ARDLEIGH SURGERY"
    assert resource["active"] is True
    assert resource["address"] == [{"postalCode": "CO7 7LD", "country": "GB"}]
    assert [t["coding"][0]["code"] for t in resource["type"]] == ["RO177", "RO76"]
    assert resource["type"][0]["coding"][0]["display"] == "PRESCRIBING COST CENTRE"


def test_the_primary_role_the_snapshot_time_and_the_last_change_date_are_recorded() -> None:
    resource = organisation_resource(
        ods_code="F81044", legal_name="Ardleigh Ltd", record=RECORD, now=NOW
    )

    assert _ext(resource, "odsPrimaryRole") == "RO177"
    assert _ext(resource, "odsSnapshotAt") == "2026-10-31T09:30:00Z"
    assert _ext(resource, "odsLastChangedAt") == "2024-05-01"


def test_each_active_link_is_a_child_with_its_code_name_and_role() -> None:
    resource = organisation_resource(
        ods_code="F81044", legal_name="Ardleigh Ltd", record=RECORD, now=NOW
    )

    assert resource["link"] == [
        {"relationship": "RE4", "code": "F81045", "display": "A PARENT PRACTICE", "role": "RO98"}
    ]


def test_an_inactive_record_is_not_active() -> None:
    inactive = replace(RECORD, status="Inactive")

    resource = organisation_resource(
        ods_code="F81044", legal_name="Ardleigh Ltd", record=inactive, now=NOW
    )

    assert resource["active"] is False


def test_an_organisation_entered_by_hand_carries_only_its_code_and_legal_name() -> None:
    resource = organisation_resource(
        ods_code="F81044", legal_name="Ardleigh Ltd", record=None, now=NOW
    )

    assert set(resource) == {"resourceType", "id", "identifier", "name"}
    assert resource["name"] == "Ardleigh Ltd"


def test_the_bundle_is_one_put_to_the_organization_id_that_the_writer_accepts() -> None:
    bundle = organisation_bundle(
        ods_code="F81044", legal_name="Ardleigh Ltd", record=RECORD, now=NOW
    )

    (entry,) = resolve_bundle(bundle)
    assert (entry.method, entry.type, entry.id) == ("PUT", "Organization", "F81044")


def test_every_element_of_the_record_round_trips_through_the_mapper() -> None:
    resource = organisation_resource(
        ods_code="F81044", legal_name="Ardleigh Ltd", record=RECORD, now=NOW
    )

    rebuilt = from_graph(
        to_graph({**resource, "meta": {"versionId": "1", "lastUpdated": "2026-10-31T09:30:00Z"}})
    )

    for key, value in resource.items():
        assert rebuilt[key] == value, key
    assert rebuilt["meta"]["versionId"] == "1"


def test_a_tenant_created_by_hand_round_trips_through_the_mapper() -> None:
    resource = organisation_resource(
        ods_code="F81044", legal_name="Ardleigh Ltd", record=None, now=NOW
    )

    rebuilt = from_graph(
        to_graph({**resource, "meta": {"versionId": "1", "lastUpdated": "2026-10-31T09:30:00Z"}})
    )

    assert {k: rebuilt[k] for k in resource} == resource
