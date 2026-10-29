"""Writing a FHIR transaction bundle through the resource store (U27): the pure resolution of
`urn:uuid:` references, and the order, the versions and the refusals of the write. The store is a
recording stand-in; what Neo4j really holds is in tests/integration/application/
test_registration_submit.py. Sample values only."""

from typing import Any

import pytest

from diucs.adapters.outbound.graph_store.bundle_writer import resolve_bundle, write_bundle
from diucs.domain.errors import NotFound, ValidationFailed


def _entry(resource_type: str, id_: str, method: str = "POST", **elements: Any) -> dict[str, Any]:
    url = resource_type if method == "POST" else f"{resource_type}/{id_}"
    return {
        "fullUrl": f"urn:uuid:{id_}",
        "resource": {"resourceType": resource_type, "id": id_, **elements},
        "request": {"method": method, "url": url},
    }


def _bundle(*entries: dict[str, Any], kind: str = "transaction") -> dict[str, Any]:
    return {"resourceType": "Bundle", "type": kind, "entry": list(entries)}


BUNDLE = _bundle(
    _entry("Organization", "org-1", name="Community Response Ltd"),
    _entry("Location", "loc-1", managingOrganization={"reference": "urn:uuid:org-1"}),
    _entry(
        "HealthcareService",
        "svc-1",
        "PUT",
        providedBy={"reference": "urn:uuid:org-1"},
        location=[{"reference": "urn:uuid:loc-1"}],
        coverageArea=[{"reference": "Location/existing-dt3"}],
    ),
)


class RecordingStore:
    def __init__(self, held: dict[tuple[str, str], str] | None = None) -> None:
        self.held = dict(held or {})
        self.puts: list[tuple[dict[str, Any], str | None]] = []

    async def get(self, type: str, id: str) -> dict[str, Any] | None:
        version = self.held.get((type, id))
        if version is None:
            return None
        return {"resourceType": type, "id": id, "meta": {"versionId": version}}

    async def put(self, resource: dict[str, Any], expected_version: str | None) -> str:
        self.puts.append((resource, expected_version))
        return "1"


def test_every_urn_reference_becomes_the_resource_type_and_id() -> None:
    entries = resolve_bundle(BUNDLE)

    location = next(entry for entry in entries if entry.type == "Location")
    assert location.resource["managingOrganization"] == {"reference": "Organization/org-1"}
    service = next(entry for entry in entries if entry.type == "HealthcareService")
    assert service.resource["providedBy"] == {"reference": "Organization/org-1"}
    assert service.resource["location"] == [{"reference": "Location/loc-1"}]
    assert service.resource["coverageArea"] == [{"reference": "Location/existing-dt3"}]


def test_resolution_does_not_change_the_bundle_it_was_given() -> None:
    before = repr(BUNDLE)

    resolve_bundle(BUNDLE)

    assert repr(BUNDLE) == before


def test_the_entries_keep_the_order_of_the_bundle_with_their_methods() -> None:
    entries = resolve_bundle(BUNDLE)

    assert [(e.method, e.type, e.id) for e in entries] == [
        ("POST", "Organization", "org-1"),
        ("POST", "Location", "loc-1"),
        ("PUT", "HealthcareService", "svc-1"),
    ]
    assert entries[0].full_url == "urn:uuid:org-1"


async def test_a_post_is_written_new_and_a_put_replaces_the_stored_version() -> None:
    store = RecordingStore({("HealthcareService", "svc-1"): "3"})

    written = await write_bundle(store, BUNDLE)

    assert [(put[0]["resourceType"], put[1]) for put in store.puts] == [
        ("Organization", None),
        ("Location", None),
        ("HealthcareService", "3"),
    ]
    assert written == {
        "urn:uuid:org-1": "Organization/org-1",
        "urn:uuid:loc-1": "Location/loc-1",
        "urn:uuid:svc-1": "HealthcareService/svc-1",
    }


async def test_the_resources_are_written_with_their_references_resolved() -> None:
    store = RecordingStore({("HealthcareService", "svc-1"): "3"})

    await write_bundle(store, BUNDLE)

    service = store.puts[2][0]
    assert service["providedBy"] == {"reference": "Organization/org-1"}


async def test_a_put_for_a_resource_that_does_not_exist_is_not_found_and_writes_nothing_more() -> (
    None
):
    store = RecordingStore()

    with pytest.raises(NotFound):
        await write_bundle(store, BUNDLE)

    assert [put[0]["resourceType"] for put in store.puts] == ["Organization", "Location"]


@pytest.mark.parametrize(
    "bundle",
    [
        _bundle(_entry("Organization", "o"), kind="batch"),
        {"resourceType": "Bundle", "type": "transaction"},
        {"resourceType": "Bundle", "type": "transaction", "entry": []},
        {"resourceType": "Organization", "id": "o"},
    ],
)
def test_only_a_transaction_bundle_with_entries_is_accepted(bundle: dict[str, Any]) -> None:
    with pytest.raises(ValidationFailed):
        resolve_bundle(bundle)


def test_an_entry_with_a_method_other_than_post_or_put_is_refused() -> None:
    with pytest.raises(ValidationFailed):
        resolve_bundle(_bundle(_entry("Organization", "o", "DELETE")))


def test_a_full_url_that_is_not_the_resource_id_is_refused() -> None:
    entry = _entry("Organization", "o")
    entry["fullUrl"] = "urn:uuid:another"
    with pytest.raises(ValidationFailed):
        resolve_bundle(_bundle(entry))


def test_two_entries_with_one_id_are_refused() -> None:
    with pytest.raises(ValidationFailed):
        resolve_bundle(_bundle(_entry("Organization", "o"), _entry("Location", "o")))


def test_a_urn_reference_to_nothing_in_the_bundle_is_refused() -> None:
    with pytest.raises(ValidationFailed):
        resolve_bundle(
            _bundle(_entry("Location", "l", managingOrganization={"reference": "urn:uuid:nope"}))
        )


def test_a_put_url_that_names_another_resource_is_refused() -> None:
    entry = _entry("HealthcareService", "svc-1", "PUT")
    entry["request"]["url"] = "HealthcareService/svc-2"
    with pytest.raises(ValidationFailed):
        resolve_bundle(_bundle(entry))


def test_a_resource_that_names_a_tenant_is_refused() -> None:
    with pytest.raises(ValidationFailed):
        resolve_bundle(_bundle(_entry("Organization", "o", tenantId="tenant-b")))


async def test_the_registration_repository_writes_a_bundle_through_its_store() -> None:
    from diucs.adapters.outbound.graph_store.registration_repository import (
        Neo4jRegistrationRepository,
    )

    store = RecordingStore({("HealthcareService", "svc-1"): "3"})
    repository = Neo4jRegistrationRepository(None, store)  # type: ignore[arg-type]

    written = await repository.write_bundle(BUNDLE)

    assert written["urn:uuid:svc-1"] == "HealthcareService/svc-1"
    assert len(store.puts) == 3
