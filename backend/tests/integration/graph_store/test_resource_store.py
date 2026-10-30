"""Integration tests for the graph writer and reader (G05, rule R10, DEC-053).

They run against the throwaway Neo4j that the F10 harness starts for the pytest session (DEC-008).
Every write goes through ResourceStore in one committed transaction, and every read happens in a
fresh session, so what the tests assert is what was really stored. All values are synthetic.
"""

import asyncio
import inspect
import json
import re
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import pytest
import pytest_asyncio
from neo4j import AsyncDriver
from neo4j.exceptions import ClientError
from neo4j.spatial import WGS84Point
from neo4j.time import Date, DateTime, Time

from diucs.adapters.outbound.graph_store import resource_store
from diucs.adapters.outbound.graph_store.mapper import RelSpec, UnknownExtension
from diucs.adapters.outbound.graph_store.queries import REGISTRY
from diucs.adapters.outbound.graph_store.resource_store import ResourceStore
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.application.tenancy import TenantNotBound, bind_tenant
from diucs.domain.codes import BASE_URL
from diucs.domain.errors import Conflict, NotAllowed, NotFound, ValidationFailed
from tests.support.neo4j import count_nodes, node_props, read_tx, wipe, write_tx
from tests.support.scoped import scoped
from tests.support.tenant_seed import contracted_container, invariant_breaks
from tests.unit.adapters.outbound.graph_store.test_mapper_backbone import (
    AREA_A_ID,
    SVC_ID,
    UCR_WEST,
)

pytestmark = pytest.mark.asyncio(loop_scope="session")

AT = datetime(2026, 10, 25, 9, 0, 0, tzinfo=UTC)
STAMP = "2026-10-25T09:00:00Z"
ORG_ID = "6b1f0c2e-3a4d-4e5f-8a9b-0c1d2e3f4a5b"
LOC_ID = "7c2a1d3f-4b5e-4f60-9b0c-1d2e3f4a5b6c"
OBS_ID = "9e4c3f5b-6d7a-4182-9d2e-3f4a5b6c7d8e"
PAT_ID = "0f5d4a6c-7e8b-4293-8e3f-4a5b6c7d8e9f"
MEASURE = f"{BASE_URL}CodeSystem/measure"
UCUM = "http://unitsofmeasure.org"
CATEGORY = f"{BASE_URL}CodeSystem/service-category"
UPRN_URL = f"{BASE_URL}StructureDefinition/uprn"


def _org(name: str = "Example Trust") -> dict[str, Any]:
    return {"resourceType": "Organization", "id": ORG_ID, "active": True, "name": name}


def _with_meta(resource: dict[str, Any], version: str) -> dict[str, Any]:
    return {**resource, "meta": {"versionId": version, "lastUpdated": STAMP}}


async def _put(driver: AsyncDriver, resource: dict[str, Any], expected: str | None) -> str:
    async def work(tx: Any) -> str:
        return await ResourceStore(tx, FixedClock(AT)).put(resource, expected)

    return await write_tx(driver, work)


async def _get(driver: AsyncDriver, type_: str, id_: str) -> dict[str, Any] | None:
    async def work(tx: Any) -> dict[str, Any] | None:
        return await ResourceStore(tx, FixedClock(AT)).get(type_, id_)

    return await read_tx(driver, work)


async def _history(driver: AsyncDriver, type_: str, id_: str) -> list[dict[str, Any]]:
    async def work(tx: Any) -> list[dict[str, Any]]:
        return await ResourceStore(tx, FixedClock(AT)).history(type_, id_)

    return await read_tx(driver, work)


async def _every_property_value(driver: AsyncDriver) -> list[Any]:
    """Every node and relationship property value in the graph, read in a fresh session."""

    async def work(tx: Any) -> list[Any]:
        nodes = await (await tx.run("MATCH (n) RETURN properties(n) AS p")).data()
        rels = await (await tx.run("MATCH ()-[r]->() RETURN properties(r) AS p")).data()
        return [value for row in [*nodes, *rels] for value in row["p"].values()]

    return await read_tx(driver, work)


def _observation() -> dict[str, Any]:
    return {
        "resourceType": "Observation",
        "id": OBS_ID,
        "status": "final",
        "code": {"coding": [{"system": MEASURE, "code": "referral-capacity"}]},
        "subject": {"reference": f"HealthcareService/{SVC_ID}"},
        "effectiveDateTime": "2026-10-25T08:00:00Z",
        "valueQuantity": {"value": 3, "unit": "{referral}", "system": UCUM, "code": "{referral}"},
    }


async def test_a_new_organization_round_trips_through_a_fresh_session(
    neo4j_driver: AsyncDriver,
) -> None:
    version = await _put(neo4j_driver, _org(), None)

    assert version == "1"
    assert await _get(neo4j_driver, "Organization", ORG_ID) == _with_meta(_org(), "1")


async def test_an_update_with_the_current_version_returns_2_and_keeps_version_1(
    neo4j_driver: AsyncDriver,
) -> None:
    await _put(neo4j_driver, _org("Before"), None)

    version = await _put(neo4j_driver, _org("After"), "1")

    assert version == "2"
    assert await count_nodes(neo4j_driver, "ResourceVersion") == 1
    assert await _history(neo4j_driver, "Organization", ORG_ID) == [_with_meta(_org("Before"), "1")]
    assert await _get(neo4j_driver, "Organization", ORG_ID) == _with_meta(_org("After"), "2")


async def test_a_stale_expected_version_raises_conflict_and_the_stored_version_is_unchanged(
    neo4j_driver: AsyncDriver,
) -> None:
    await _put(neo4j_driver, _org("First"), None)
    await _put(neo4j_driver, _org("Second"), "1")

    with pytest.raises(Conflict):
        await _put(neo4j_driver, _org("Stale"), "1")

    stored = await _get(neo4j_driver, "Organization", ORG_ID)
    assert stored == _with_meta(_org("Second"), "2")


async def test_creating_over_an_existing_id_raises_conflict(neo4j_driver: AsyncDriver) -> None:
    await _put(neo4j_driver, _org(), None)

    with pytest.raises(Conflict):
        await _put(neo4j_driver, _org("Again"), None)


async def test_a_second_put_of_an_observation_raises_not_allowed(neo4j_driver: AsyncDriver) -> None:
    await _put(neo4j_driver, _observation(), None)

    with pytest.raises(NotAllowed):
        await _put(neo4j_driver, _observation(), "1")


async def test_removing_one_of_two_available_times_leaves_one_child_node_and_keeps_concepts(
    neo4j_driver: AsyncDriver,
) -> None:
    await _put(neo4j_driver, UCR_WEST, None)
    assert await count_nodes(neo4j_driver, "HealthcareService_AvailableTime") == 2
    concepts_before = await count_nodes(neo4j_driver, "Concept")

    one_slot = {**UCR_WEST, "availableTime": [UCR_WEST["availableTime"][0]]}
    await _put(neo4j_driver, one_slot, "1")

    assert await count_nodes(neo4j_driver, "HealthcareService_AvailableTime") == 1
    assert await count_nodes(neo4j_driver, "Concept") == concepts_before
    assert await _get(neo4j_driver, "HealthcareService", SVC_ID) == _with_meta(one_slot, "2")


async def test_a_reference_to_a_missing_resource_is_a_placeholder_until_it_is_written(
    neo4j_driver: AsyncDriver,
) -> None:
    await _put(neo4j_driver, UCR_WEST, None)

    placeholder = await node_props(neo4j_driver, "Organization", id=ORG_ID)
    assert placeholder["placeholder"] is True

    await _put(neo4j_driver, _org(), None)

    written = await node_props(neo4j_driver, "Organization", id=ORG_ID)
    assert "placeholder" not in written
    assert written["name"] == "Example Trust"


async def test_clearing_a_patient_value_leaves_no_version_and_no_copy_of_it(
    neo4j_driver: AsyncDriver,
) -> None:
    # Patient.address is not a mapped element (G04), so the address-like value is the uprn.
    uprn = "100000000001"
    patient = {
        "resourceType": "Patient",
        "id": PAT_ID,
        "active": True,
        "extension": [{"url": UPRN_URL, "valueString": uprn}],
    }
    await _put(neo4j_driver, patient, None)
    assert uprn in str(await _every_property_value(neo4j_driver))

    cleared = {key: value for key, value in patient.items() if key != "extension"}
    await _put(neo4j_driver, cleared, "1")

    assert await count_nodes(neo4j_driver, "ResourceVersion") == 0
    assert await _history(neo4j_driver, "Patient", PAT_ID) == []
    assert uprn not in str(await _every_property_value(neo4j_driver))
    assert await _get(neo4j_driver, "Patient", PAT_ID) == _with_meta(cleared, "2")


async def test_a_location_position_is_stored_as_a_point(neo4j_driver: AsyncDriver) -> None:
    location = {
        "resourceType": "Location",
        "id": LOC_ID,
        "status": "active",
        "name": "Example Site",
        "position": {"latitude": 50.61, "longitude": -2.45},
    }
    await _put(neo4j_driver, location, None)

    props = await node_props(neo4j_driver, "Location", id=LOC_ID)
    point = props["position"]
    assert isinstance(point, WGS84Point)
    assert point.latitude == 50.61
    assert point.longitude == -2.45
    assert await _get(neo4j_driver, "Location", LOC_ID) == _with_meta(location, "1")


async def test_the_ucr_west_service_round_trips_exactly(neo4j_driver: AsyncDriver) -> None:
    await _put(neo4j_driver, UCR_WEST, None)

    assert await _get(neo4j_driver, "HealthcareService", SVC_ID) == _with_meta(UCR_WEST, "1")


async def test_a_datetime_keeps_its_text_and_offset_in_the_graph(
    neo4j_driver: AsyncDriver,
) -> None:
    observation = {**_observation(), "effectiveDateTime": "2026-10-25T01:30:00.5+01:00"}
    await _put(neo4j_driver, observation, None)

    props = await node_props(neo4j_driver, "Observation", id=OBS_ID)
    stored = props["effectiveDateTime"]
    assert isinstance(stored, DateTime)
    assert stored.utcoffset().total_seconds() == 3600
    assert await _get(neo4j_driver, "Observation", OBS_ID) == _with_meta(observation, "1")


@pytest.mark.parametrize(
    "text",
    ["2026-10-25T08:00:00+00:00", "2026-10-25T08:00:00.000Z", "2026-10", "2026-13-40"],
)
async def test_text_that_would_not_come_back_identically_is_refused(
    neo4j_driver: AsyncDriver, text: str
) -> None:
    observation = {**_observation(), "effectiveDateTime": text}

    with pytest.raises(ValidationFailed):
        await _put(neo4j_driver, observation, None)

    assert await count_nodes(neo4j_driver, "Observation") == 0


async def test_a_shared_concept_with_another_display_is_refused_and_nothing_is_written(
    neo4j_driver: AsyncDriver,
) -> None:
    first = {
        "resourceType": "HealthcareService",
        "id": SVC_ID,
        "active": True,
        "category": [{"coding": [{"system": CATEGORY, "code": "shared", "display": "Shared"}]}],
    }
    await _put(neo4j_driver, first, None)
    other = {
        "resourceType": "Organization",
        "id": ORG_ID,
        "active": True,
        "type": {"coding": [{"system": CATEGORY, "code": "shared", "display": "Different"}]},
    }

    with pytest.raises(ValidationFailed):
        await _put(neo4j_driver, other, None)

    assert await _get(neo4j_driver, "Organization", ORG_ID) is None
    assert (await node_props(neo4j_driver, "Concept", code="shared"))["display"] == "Shared"


async def test_a_shared_concept_without_a_display_takes_one_from_a_later_resource(
    neo4j_driver: AsyncDriver,
) -> None:
    bare = {
        "resourceType": "HealthcareService",
        "id": SVC_ID,
        "active": True,
        "category": [{"coding": [{"system": CATEGORY, "code": "later"}]}],
    }
    await _put(neo4j_driver, bare, None)
    named = {
        "resourceType": "Organization",
        "id": ORG_ID,
        "active": True,
        "type": {"coding": [{"system": CATEGORY, "code": "later", "display": "Later"}]},
    }
    await _put(neo4j_driver, named, None)

    assert (await node_props(neo4j_driver, "Concept", code="later"))["display"] == "Later"


async def test_an_element_named_key_is_refused_and_nothing_is_written(
    neo4j_driver: AsyncDriver,
) -> None:
    with pytest.raises(ValidationFailed):
        await _put(neo4j_driver, {**_org(), "key": "Organization/other"}, None)

    assert await count_nodes(neo4j_driver, "Resource") == 0


async def test_meta_in_the_input_is_refused(neo4j_driver: AsyncDriver) -> None:
    with pytest.raises(ValidationFailed):
        await _put(neo4j_driver, {**_org(), "meta": {"versionId": "9"}}, None)


@pytest.mark.parametrize("bad_id", ["a#b", "a|b", "a/b", "a@1", ""])
async def test_an_id_that_is_not_a_fhir_id_is_refused(
    neo4j_driver: AsyncDriver, bad_id: str
) -> None:
    with pytest.raises(ValidationFailed):
        await _put(neo4j_driver, {**_org(), "id": bad_id}, None)


async def test_two_writers_racing_on_one_version_let_exactly_one_win(
    neo4j_driver: AsyncDriver,
) -> None:
    await _put(neo4j_driver, _org(), None)

    results = await asyncio.gather(
        _put(neo4j_driver, _org("Left"), "1"),
        _put(neo4j_driver, _org("Right"), "1"),
        return_exceptions=True,
    )

    assert sorted(type(item).__name__ for item in results) == ["Conflict", "str"]
    assert await _get(neo4j_driver, "Organization", ORG_ID) is not None
    assert await count_nodes(neo4j_driver, "ResourceVersion") == 1


async def test_a_missing_resource_reads_as_none_and_has_no_history(
    neo4j_driver: AsyncDriver,
) -> None:
    assert await _get(neo4j_driver, "Organization", ORG_ID) is None
    assert await _history(neo4j_driver, "Organization", ORG_ID) == []


async def test_no_stored_property_is_a_map_a_list_of_maps_or_a_json_string(
    neo4j_driver: AsyncDriver,
) -> None:
    await _put(neo4j_driver, UCR_WEST, None)
    await _put(neo4j_driver, _observation(), None)

    values = await _every_property_value(neo4j_driver)

    for value in values:
        assert not isinstance(value, dict)
        if isinstance(value, list):
            assert not any(isinstance(item, dict) for item in value)
        if isinstance(value, str):
            # A UCUM annotation such as {referral} is text, not JSON; a JSON object or array is not.
            try:
                parsed = json.loads(value)
            except ValueError:
                continue
            assert not isinstance(parsed, dict | list)


async def test_a_stored_filter_code_is_written_with_its_coded_value(
    neo4j_driver: AsyncDriver,
) -> None:
    # H-24: measureCode is a derived copy of the first code; the same put must store both.
    await _put(neo4j_driver, _observation(), None)

    props = await node_props(neo4j_driver, "Observation", id=OBS_ID)
    assert props["measureCode"] == "referral-capacity"
    assert await _get(neo4j_driver, "Observation", OBS_ID) == _with_meta(_observation(), "1")


async def test_a_refused_create_leaves_no_node_even_if_the_caller_commits(
    neo4j_driver: AsyncDriver,
) -> None:
    async def swallow(tx: Any) -> str:
        try:
            await ResourceStore(tx, FixedClock(AT)).put(_org(), "1")
        except Conflict:
            return "refused"
        return "written"

    assert await write_tx(neo4j_driver, swallow) == "refused"
    assert await count_nodes(neo4j_driver, "Resource") == 0


async def test_a_refused_datetime_leaves_no_node_even_if_the_caller_commits(
    neo4j_driver: AsyncDriver,
) -> None:
    bad = {**_observation(), "effectiveDateTime": "2026-10-25T08:00:00+00:00"}

    async def swallow(tx: Any) -> str:
        try:
            await ResourceStore(tx, FixedClock(AT)).put(bad, None)
        except ValidationFailed:
            return "refused"
        return "written"

    assert await write_tx(neo4j_driver, swallow) == "refused"
    assert await count_nodes(neo4j_driver, "Resource") == 0


# TEN-009 (DEC-164): every node the store writes carries the tenant, every statement is anchored on
# it, and another tenant's resource reads as absent. The first group is about the statements and
# needs no database; the second runs on the shared harness container with the run tenant bound; the
# third runs two tenants with the same ids on a private container whose superseded single-property
# keys are dropped (the schema after TEN-032, as the generated test does).

RES_TEMPLATES = frozenset(
    {
        "Q-RES-CLEAR-OWNED",
        "Q-RES-CLEAR-ROOT-RELS",
        "Q-RES-GET",
        "Q-RES-HISTORY",
        "Q-RES-LINK-SHARED",
        "Q-RES-LOAD-NODES",
        "Q-RES-LOAD-RELS",
        "Q-RES-LOCK",
        "Q-RES-MERGE-NODES",
        "Q-RES-MERGE-RELS",
        "Q-RES-SET-POSITION",
        "Q-RES-SHARED-CREATE",
        "Q-RES-SHARED-FILL",
        "Q-RES-SHARED-READ",
        "Q-RES-UPSERT-NODE",
        "Q-RES-UPSERT-ROOT",
    }
)
TENANT_A = "tenant-a"
TENANT_B = "tenant-b"
# A node pattern: `(`, an optional variable, optional labels (a label expression may use `|`), an
# optional property map, `)`; not a function call (no word character before the parenthesis).
_NODE_PATTERN = re.compile(r"(?<![\w`])\(\s*\w*\s*(?::[\w|:]+)?\s*(?:\{[^}]*\})?\s*\)")


def _template_text(template_id: str) -> str:
    template = REGISTRY.template(template_id)
    insert = template.scenario.insert if template.scenario is not None else ""
    return REGISTRY.instance(template_id, insert).cypher


async def test_the_resource_store_registers_exactly_these_templates() -> None:
    registered = {t for t in REGISTRY.template_ids() if t.startswith("Q-RES-")}

    assert registered == RES_TEMPLATES


@pytest.mark.parametrize("template_id", sorted(RES_TEMPLATES))
async def test_a_resource_store_template_is_converted(
    template_id: str,
) -> None:
    assert template_id in REGISTRY.template_ids()
    template = REGISTRY.template(template_id)

    assert "tenantId: $tenant" in template.cypher
    assert template.scenario is not None


@pytest.mark.parametrize("template_id", sorted(RES_TEMPLATES))
async def test_every_node_pattern_with_a_label_or_a_key_names_the_tenant(template_id: str) -> None:
    """A cheap look at the text (the generated test is the proof): each node pattern that has a
    label or a property map names `tenantId: $tenant`. A bare variable bound earlier need not."""
    assert template_id in REGISTRY.template_ids()
    text = _template_text(template_id)
    patterns = [
        m.group(0) for m in _NODE_PATTERN.finditer(text) if ":" in m.group(0) or "{" in m.group(0)
    ]

    assert patterns, template_id
    for pattern in patterns:
        assert "tenantId: $tenant" in pattern or "tenantId = $tenant" in pattern, (
            template_id,
            pattern,
        )


async def test_no_resource_store_statement_matches_the_whole_graph_by_a_property_alone() -> None:
    """The label-less matches were typed or anchored on a typed root: no statement is a scan of
    every node (`MATCH (c) WHERE c.key ...`)."""
    for template_id in sorted(RES_TEMPLATES):
        text = _template_text(template_id)
        assert re.search(r"MATCH \(\w+\) WHERE", text) is None, template_id


async def test_the_idempotency_pair_and_the_put_argument_are_gone() -> None:
    assert "Q-RES-IDEM-GET" not in REGISTRY.template_ids()
    assert "Q-RES-IDEM-RECORD" not in REGISTRY.template_ids()
    assert "idempotency_key" not in inspect.signature(ResourceStore.put).parameters
    assert not hasattr(resource_store, "_check_idempotency_key")


@pytest.mark.parametrize("name", ["tenantId", "sourceTenantId"])
async def test_the_store_refuses_and_strips_the_tenant_names(name: str) -> None:
    assert name in resource_store.RESERVED_PROPERTIES
    with pytest.raises(ValidationFailed):
        resource_store._node_props_to_db("Organization/o1", {"name": "x", name: "tenant-b"})
    assert resource_store._props_from_db({"name": "x", name: "tenant-a"}) == {"name": "x"}


async def _labels_and_tenants(driver: AsyncDriver) -> list[tuple[str, Any]]:
    async def work(tx: Any) -> list[tuple[str, Any]]:
        rows = await (
            await tx.run(
                "MATCH (n) WHERE NOT n:Migration RETURN labels(n) AS labels, n.tenantId AS t"
            )
        ).data()
        return [(":".join(sorted(r["labels"])), r["t"]) for r in rows]

    return await read_tx(driver, work)


def _rich_service() -> dict[str, Any]:
    return {**UCR_WEST, "id": SVC_ID}


async def test_every_node_the_store_writes_carries_the_run_tenant(
    neo4j_driver: AsyncDriver, tenant_id: str
) -> None:
    organization = {
        **_org(),
        "identifier": [{"system": "https://fhir.nhs.uk/Id/ods-organization-code", "value": "X1A"}],
    }
    await _put(neo4j_driver, organization, None)
    await _put(neo4j_driver, _rich_service(), None)
    await _put(neo4j_driver, _rich_service(), "1")

    found = await _labels_and_tenants(neo4j_driver)

    labels = {label for label, _ in found}
    for expected in (
        "HealthcareService:Resource",
        "Organization:Resource",
        "HealthcareService_AvailableTime",
        "Concept",
        "CodeSystem",
        "Identifier",
        "ResourceVersion",
        "ResourceVersionPart",
    ):
        assert expected in labels, expected
    # The reference targets that do not exist yet are placeholders, stamped like the rest.
    assert "Location:Resource" in labels
    assert {tenant for _, tenant in found} == {tenant_id}


async def test_an_update_keeps_the_stamp_on_the_root_the_children_and_the_version_copy(
    neo4j_driver: AsyncDriver, tenant_id: str
) -> None:
    await _put(neo4j_driver, _rich_service(), None)
    await _put(neo4j_driver, {**_rich_service(), "name": "Renamed"}, "1")

    root = await node_props(neo4j_driver, "HealthcareService", id=SVC_ID)
    version = await node_props(neo4j_driver, "ResourceVersion", key=f"HealthcareService/{SVC_ID}@1")

    assert root["tenantId"] == tenant_id
    assert version["tenantId"] == tenant_id
    assert root["name"] == "Renamed"
    assert {tenant for _, tenant in await _labels_and_tenants(neo4j_driver)} == {tenant_id}


@pytest.mark.parametrize("element", ["tenantId", "sourceTenantId"])
async def test_a_resource_cannot_carry_the_tenant_so_it_cannot_forge_or_overwrite_the_stamp(
    neo4j_driver: AsyncDriver, tenant_id: str, element: str
) -> None:
    with pytest.raises(ValidationFailed):
        await _put(neo4j_driver, {**_org(), element: TENANT_B}, None)
    assert await count_nodes(neo4j_driver, "Resource") == 0

    await _put(neo4j_driver, _org("Before"), None)
    with pytest.raises(ValidationFailed):
        await _put(neo4j_driver, {**_org("After"), element: TENANT_B}, "1")

    stored = await node_props(neo4j_driver, "Organization", id=ORG_ID)
    assert stored["tenantId"] == tenant_id
    assert stored["name"] == "Before"
    assert await _get(neo4j_driver, "Organization", ORG_ID) == _with_meta(_org("Before"), "1")


async def test_a_resource_with_a_tenant_extension_is_refused_and_writes_nothing(
    neo4j_driver: AsyncDriver,
) -> None:
    forged = {
        **_org(),
        "extension": [{"url": f"{BASE_URL}StructureDefinition/tenantId", "valueString": TENANT_B}],
    }

    with pytest.raises(UnknownExtension):
        await _put(neo4j_driver, forged, None)
    assert await count_nodes(neo4j_driver, "Resource") == 0


async def test_a_read_never_gives_back_the_stamp_as_an_element(neo4j_driver: AsyncDriver) -> None:
    await _put(neo4j_driver, _rich_service(), None)
    await _put(neo4j_driver, {**_rich_service(), "name": "Renamed"}, "1")

    current = await _get(neo4j_driver, "HealthcareService", SVC_ID)
    history = await _history(neo4j_driver, "HealthcareService", SVC_ID)

    assert current is not None
    assert "tenantId" not in json.dumps(current)
    assert "tenantId" not in json.dumps(history)
    assert history == [_with_meta({**_rich_service()}, "1")]


async def test_a_repeated_put_leaves_one_in_system_edge_per_concept(
    neo4j_driver: AsyncDriver,
) -> None:
    await _put(neo4j_driver, _observation(), None)
    await _put(neo4j_driver, _rich_service(), None)
    await _put(neo4j_driver, {**_rich_service(), "name": "Two"}, "1")
    await _put(neo4j_driver, {**_rich_service(), "name": "Three"}, "2")

    async def work(tx: Any) -> list[dict[str, Any]]:
        return await (
            await tx.run(
                "MATCH (c:Concept)-[r:IN_SYSTEM]->(s:CodeSystem) "
                "RETURN c.key AS concept, count(r) AS edges"
            )
        ).data()

    rows = await read_tx(neo4j_driver, work)

    assert rows
    assert {row["edges"] for row in rows} == {1}
    assert await count_nodes(neo4j_driver, "Concept") == len(rows)


@pytest.mark.no_tenant
async def test_with_no_tenant_bound_every_operation_is_refused_before_any_cypher(
    neo4j_driver: AsyncDriver,
) -> None:
    async def put(tx: Any) -> str:
        return await ResourceStore(tx, FixedClock(AT)).put(_org(), None)

    async def get(tx: Any) -> Any:
        return await ResourceStore(tx, FixedClock(AT)).get("Organization", ORG_ID)

    async def exists(tx: Any) -> bool:
        return await ResourceStore(tx, FixedClock(AT)).exists("Organization", ORG_ID)

    async def history(tx: Any) -> Any:
        return await ResourceStore(tx, FixedClock(AT)).history("Organization", ORG_ID)

    with pytest.raises(TenantNotBound):
        await write_tx(neo4j_driver, put)
    for read in (get, exists, history):
        with pytest.raises(TenantNotBound):
            await read_tx(neo4j_driver, read)
    assert await count_nodes(neo4j_driver, "Resource") == 0


# Two tenants with the same ids, on a private container with the superseded keys dropped.


@pytest_asyncio.fixture(scope="module", loop_scope="session")
async def two_tenant_driver() -> AsyncIterator[AsyncDriver]:
    async with contracted_container() as driver:
        yield driver


@pytest_asyncio.fixture(loop_scope="session")
async def two(two_tenant_driver: AsyncDriver) -> AsyncIterator[AsyncDriver]:
    await wipe(two_tenant_driver)
    yield two_tenant_driver
    await wipe(two_tenant_driver)


async def _put_as(
    driver: AsyncDriver, tenant: str, resource: dict[str, Any], expected: str | None
) -> str:
    with bind_tenant(tenant):
        return await _put(driver, resource, expected)


async def _get_as(driver: AsyncDriver, tenant: str, type_: str, id_: str) -> dict[str, Any] | None:
    with bind_tenant(tenant):
        return await _get(driver, type_, id_)


async def _history_as(
    driver: AsyncDriver, tenant: str, type_: str, id_: str
) -> list[dict[str, Any]]:
    with bind_tenant(tenant):
        return await _history(driver, type_, id_)


async def _exists_as(driver: AsyncDriver, tenant: str, type_: str, id_: str) -> bool:
    async def work(tx: Any) -> bool:
        return await ResourceStore(tx, FixedClock(AT)).exists(type_, id_)

    with bind_tenant(tenant):
        return await read_tx(driver, work)


async def _count(driver: AsyncDriver, tenant: str, where: str) -> int:
    async def work(tx: Any) -> int:
        record = await (
            await tx.run(
                f"MATCH (n) WHERE n.tenantId = $t AND {where} RETURN count(n) AS c", t=tenant
            )
        ).single()
        assert record is not None
        return int(record["c"])

    return await read_tx(driver, work)


async def test_another_tenants_resource_reads_as_absent_and_the_same_id_is_its_own(
    two: AsyncDriver,
) -> None:
    await _put_as(two, TENANT_A, _org("Of A"), None)

    assert await _get_as(two, TENANT_B, "Organization", ORG_ID) is None
    assert await _exists_as(two, TENANT_B, "Organization", ORG_ID) is False
    assert await _history_as(two, TENANT_B, "Organization", ORG_ID) == []

    assert await _put_as(two, TENANT_B, _org("Of B"), None) == "1"
    assert await _get_as(two, TENANT_A, "Organization", ORG_ID) == _with_meta(_org("Of A"), "1")
    assert await _get_as(two, TENANT_B, "Organization", ORG_ID) == _with_meta(_org("Of B"), "1")
    assert await invariant_breaks_of(two) == ([], [])


async def invariant_breaks_of(driver: AsyncDriver) -> tuple[list[str], list[str]]:
    return await read_tx(driver, invariant_breaks)


async def test_one_tenant_cannot_update_or_conflict_with_the_others_version(
    two: AsyncDriver,
) -> None:
    await _put_as(two, TENANT_A, _org("Of A"), None)

    with pytest.raises(Conflict):
        await _put_as(two, TENANT_B, _org("Of B"), "1")
    assert await _get_as(two, TENANT_B, "Organization", ORG_ID) is None

    await _put_as(two, TENANT_B, _org("Of B"), None)
    assert await _put_as(two, TENANT_B, _org("B two"), "1") == "2"
    assert await _get_as(two, TENANT_A, "Organization", ORG_ID) == _with_meta(_org("Of A"), "1")
    assert await _history_as(two, TENANT_A, "Organization", ORG_ID) == []
    assert await _history_as(two, TENANT_B, "Organization", ORG_ID) == [
        _with_meta(_org("Of B"), "1")
    ]


async def test_an_update_in_one_tenant_clears_only_its_own_children_relationships_and_versions(
    two: AsyncDriver,
) -> None:
    await _put_as(two, TENANT_A, _rich_service(), None)
    await _put_as(two, TENANT_B, _rich_service(), None)
    before_b = (
        await _count(two, TENANT_B, "n:HealthcareService_AvailableTime"),
        await _count(two, TENANT_B, "n:Resource"),
    )
    smaller = {**_rich_service(), "availableTime": [_rich_service()["availableTime"][0]]}
    del smaller["coverageArea"]

    await _put_as(two, TENANT_A, smaller, "1")

    assert await _count(two, TENANT_A, "n:HealthcareService_AvailableTime") == 1
    assert (
        await _count(two, TENANT_B, "n:HealthcareService_AvailableTime"),
        await _count(two, TENANT_B, "n:Resource"),
    ) == before_b
    assert await _count(two, TENANT_B, "n:ResourceVersion") == 0
    assert await _count(two, TENANT_A, "n:ResourceVersion") == 1
    assert await _get_as(two, TENANT_B, "HealthcareService", SVC_ID) == _with_meta(
        _rich_service(), "1"
    )
    assert await invariant_breaks_of(two) == ([], [])


async def test_each_tenant_has_its_own_concepts_and_a_display_never_crosses(
    two: AsyncDriver,
) -> None:
    def observation(display: str | None) -> dict[str, Any]:
        coding: dict[str, Any] = {"system": MEASURE, "code": "referral-capacity"}
        if display is not None:
            coding["display"] = display
        return {**_observation(), "code": {"coding": [coding]}}

    await _put_as(two, TENANT_A, observation(None), None)
    await _put_as(two, TENANT_B, observation("Shown to B"), None)

    assert await _count(two, TENANT_A, "n:Concept") == 1
    assert await _count(two, TENANT_B, "n:Concept") == 1
    assert await _count(two, TENANT_A, "n:Concept AND n.display IS NULL") == 1
    assert await _count(two, TENANT_B, "n:Concept AND n.display = 'Shown to B'") == 1
    assert await _count(two, TENANT_A, "n:CodeSystem") == 1
    assert await _count(two, TENANT_B, "n:CodeSystem") == 1

    # B's display does not refuse A's put with another one, and A's later display does not fill B's.
    await _put_as(two, TENANT_A, {**observation("Shown to A"), "id": "obs-two"}, None)
    assert await _count(two, TENANT_A, "n:Concept AND n.display = 'Shown to A'") == 1
    assert await _count(two, TENANT_B, "n:Concept AND n.display = 'Shown to B'") == 1
    assert await invariant_breaks_of(two) == ([], [])


async def test_a_reference_target_that_does_not_exist_is_a_placeholder_of_each_tenant(
    two: AsyncDriver,
) -> None:
    await _put_as(two, TENANT_A, _rich_service(), None)
    await _put_as(two, TENANT_B, _rich_service(), None)
    location = f"Location/{AREA_A_ID}"

    assert await _count(two, TENANT_A, f"n.key = '{location}' AND n.placeholder") == 1
    assert await _count(two, TENANT_B, f"n.key = '{location}' AND n.placeholder") == 1

    await _put_as(
        two, TENANT_A, {"resourceType": "Location", "id": AREA_A_ID, "name": "Area"}, None
    )
    assert await _get_as(two, TENANT_A, "Location", AREA_A_ID) is not None
    assert await _get_as(two, TENANT_B, "Location", AREA_A_ID) is None
    assert await invariant_breaks_of(two) == ([], [])


# Key lookups must not slow as tenants are added (audit A section 8 item 4). Database hits of one
# tenant's statement with 1, 10 and 50 tenants in the graph. The statements anchored on the typed
# root (the resource's own key) must not grow with the other tenants' data.


async def _db_hits(driver: AsyncDriver, text: str, **params: Any) -> int:
    async with driver.session() as session:
        tx = scoped(await session.begin_transaction())
        try:
            summary = await (await tx.run(f"PROFILE {text}", **params)).consume()
        finally:
            await tx.rollback()
    profile = summary.profile
    assert profile is not None

    def total(node: dict[str, Any]) -> int:
        return int(node.get("dbHits", 0)) + sum(total(c) for c in node.get("children", []))

    return total(profile)


async def _fill_tenants(driver: AsyncDriver, tenants: range) -> None:
    async def work(tx: Any) -> None:
        await (
            await tx.run(
                "UNWIND $tenants AS t UNWIND range(1, 8) AS i "
                "CREATE (r:Resource:Organization {key: 'Organization/o' + i, "
                "id: 'o' + i + '-' + t, tenantId: 't' + t, name: 'x', versionId: '1'}) "
                "CREATE (c:Organization_Contact {key: 'Organization/o' + i + '#contact[0]', "
                "tenantId: 't' + t}) "
                "CREATE (r)-[:HAS_CONTACT {fhirPath: 'Organization.contact'}]->(c)",
                tenants=list(tenants),
            )
        ).consume()

    await write_tx(driver, work)


async def test_key_lookups_of_one_resource_do_not_grow_with_the_number_of_tenants(
    two: AsyncDriver,
) -> None:
    probes: dict[str, dict[str, Any]] = {
        "Q-RES-GET": {"key": "Organization/o3", "type": "Organization"},
        "Q-RES-HISTORY": {"key": "Organization/o3"},
        "Q-RES-CLEAR-ROOT-RELS": {"key": "Organization/o3"},
        "Q-RES-CLEAR-OWNED": {"key": "Organization/o3", "prefix": "Organization/o3#"},
        "Q-RES-LOAD-NODES": {
            "resourceKey": "Organization/o3",
            "key": "Organization/o3",
            "prefix": "Organization/o3#",
        },
        "Q-RES-LOAD-RELS": {
            "resourceKey": "Organization/o3",
            "key": "Organization/o3",
            "prefix": "Organization/o3#",
        },
    }
    hits: dict[int, dict[str, int]] = {}
    filled = 0
    for tenants in (1, 10, 50):
        await _fill_tenants(two, range(filled, tenants))
        filled = tenants
        hits[tenants] = {
            template_id: await _db_hits(two, _template_text(template_id), tenant="t0", **params)
            for template_id, params in probes.items()
        }

    for template_id in probes:
        assert hits[50][template_id] <= hits[1][template_id] * 1.25 + 4, (template_id, hits)


# The refusals and the failures of the store, each reached: the branches TEN-009 leaves in place.


async def test_a_label_that_is_not_a_plain_name_is_refused() -> None:
    with pytest.raises(ValidationFailed):
        resource_store._labels_text(("Not A Label",))


async def test_a_type_and_an_id_that_are_not_fhir_are_refused(neo4j_driver: AsyncDriver) -> None:
    with pytest.raises(ValidationFailed):
        await _get(neo4j_driver, "lower", "x")
    with pytest.raises(ValidationFailed):
        await _put(neo4j_driver, {"resourceType": 5, "id": "x"}, None)
    with pytest.raises(ValidationFailed):
        await _put(neo4j_driver, {"resourceType": "Organization", "id": "not an id!"}, None)


async def test_a_value_the_store_cannot_write_or_read_back_is_refused() -> None:
    with pytest.raises(ValidationFailed):
        resource_store._to_db({"a": 1}, "field")
    with pytest.raises(ValidationFailed):
        resource_store._from_db(object())
    with pytest.raises(ValidationFailed):
        resource_store._format(DateTime(2026, 10, 25, 9, 0, 0))
    with pytest.raises(ValidationFailed):
        resource_store._format("2026-10-25")
    assert resource_store._format(Time(9, 30, 5)) == "09:30:05"
    assert resource_store._format(Date(2026, 10, 25)) == "2026-10-25"


async def test_a_relationship_with_a_missing_end_is_not_found_and_links_nothing(
    neo4j_driver: AsyncDriver,
) -> None:
    async def work(tx: Any) -> None:
        store = ResourceStore(tx, FixedClock(AT))
        with pytest.raises(NotFound):
            await store._write_rels([RelSpec("PART_OF", "Organization/a", "Organization/b", {})])
        with pytest.raises(NotFound):
            await store._link_shared([RelSpec("IN_SYSTEM", "Concept|s|c", "CodeSystem|s", {})])

    await write_tx(neo4j_driver, work)


async def test_loading_a_resource_that_is_not_there_is_not_found(neo4j_driver: AsyncDriver) -> None:
    async def work(tx: Any) -> None:
        with pytest.raises(NotFound):
            await ResourceStore(tx, FixedClock(AT))._load("Organization/none", "Organization")

    await read_tx(neo4j_driver, work)


async def test_on_the_production_schema_a_second_tenants_same_id_is_a_conflict(
    neo4j_driver: AsyncDriver, other_tenant_id: str
) -> None:
    """The single-property key `resource_id` stays until TEN-032, so the second tenant cannot take
    an id the first holds there (DEC-164 item 10): `Conflict`, and the first one's is unchanged."""
    await _put(neo4j_driver, _org("Of the run tenant"), None)

    with pytest.raises(Conflict):
        await _put_as(neo4j_driver, other_tenant_id, _org("Of the other"), None)

    assert await _get(neo4j_driver, "Organization", ORG_ID) == _with_meta(
        _org("Of the run tenant"), "1"
    )


async def test_a_database_error_that_is_not_a_constraint_passes_through() -> None:
    class Failing:
        async def run(self, query: str, parameters: Any = None, **kwargs: Any) -> Any:
            raise ClientError("a statement failure that is not a constraint")

    with pytest.raises(ClientError):
        await ResourceStore(Failing(), FixedClock(AT)).put(_org(), None)  # type: ignore[arg-type]


async def test_a_local_relationship_of_the_tenant_is_not_an_element_of_the_resource(
    neo4j_driver: AsyncDriver, tenant_id: str
) -> None:
    await _put(neo4j_driver, _org(), None)

    async def link(tx: Any) -> None:
        await (
            await tx.run(
                "MATCH (o:Organization {key: $key, tenantId: $tenant}) "
                "CREATE (o)-[:CHANNEL]->(:Concept {key: 'Concept|c|t', tenantId: $tenant})",
                key=f"Organization/{ORG_ID}",
                tenant=tenant_id,
            )
        ).consume()

    await write_tx(neo4j_driver, link)

    assert await _get(neo4j_driver, "Organization", ORG_ID) == _with_meta(_org(), "1")


# Round 2 (verifier finding): a database written before TEN-009 holds more than one IN_SYSTEM edge
# per concept, because every put created another. A put must work on it and leave the same links.


async def _concept_links(driver: AsyncDriver) -> list[tuple[str, str, int]]:
    """(concept, code system, edges) for every concept that has an edge to a code system."""

    async def work(tx: Any) -> list[tuple[str, str, int]]:
        rows = await (
            await tx.run(
                "MATCH (c:Concept)-[r:IN_SYSTEM]->(s:CodeSystem) "
                "RETURN c.key AS c, s.key AS s, count(r) AS edges ORDER BY c, s"
            )
        ).data()
        return [(r["c"], r["s"], int(r["edges"])) for r in rows]

    return await read_tx(driver, work)


async def _duplicate_every_edge(driver: AsyncDriver, extra: int) -> None:
    async def work(tx: Any) -> None:
        await (
            await tx.run(
                "UNWIND range(1, $extra) AS i MATCH (c:Concept)-[:IN_SYSTEM]->(s:CodeSystem) "
                "CREATE (c)-[:IN_SYSTEM]->(s)",
                extra=extra,
            )
        ).consume()

    await write_tx(driver, work)


@pytest.mark.parametrize("extra", [1, 2])
async def test_a_put_on_concepts_that_already_have_duplicate_edges_succeeds_and_keeps_the_links(
    neo4j_driver: AsyncDriver, extra: int
) -> None:
    await _put(neo4j_driver, _rich_service(), None)
    before = await _concept_links(neo4j_driver)
    await _duplicate_every_edge(neo4j_driver, extra)
    assert {edges for _, _, edges in await _concept_links(neo4j_driver)} == {1 + extra}

    version = await _put(neo4j_driver, {**_rich_service(), "name": "Renamed"}, "1")

    assert version == "2"
    assert await _get(neo4j_driver, "HealthcareService", SVC_ID) == _with_meta(
        {**_rich_service(), "name": "Renamed"}, "2"
    )
    after = await _concept_links(neo4j_driver)
    assert [(c, s) for c, s, _ in after] == [(c, s) for c, s, _ in before]
    # The store adds no edge, and does not delete the legacy ones.
    assert {edges for _, _, edges in after} == {1 + extra}


async def test_a_concept_whose_code_system_is_missing_is_still_not_found(
    neo4j_driver: AsyncDriver,
) -> None:
    await _put(neo4j_driver, _observation(), None)

    async def drop_systems(tx: Any) -> None:
        await (await tx.run("MATCH (s:CodeSystem) DETACH DELETE s")).consume()

    await write_tx(neo4j_driver, drop_systems)

    async def work(tx: Any) -> None:
        store = ResourceStore(tx, FixedClock(AT))
        with pytest.raises(NotFound):
            await store._link_shared(
                [
                    RelSpec(
                        "IN_SYSTEM",
                        f"Concept|{MEASURE}|referral-capacity",
                        f"CodeSystem|{MEASURE}",
                        {},
                    )
                ]
            )

    await write_tx(neo4j_driver, work)


async def test_the_same_pair_twice_in_one_put_is_linked_once(neo4j_driver: AsyncDriver) -> None:
    twice = {
        **_observation(),
        "code": {"coding": [{"system": MEASURE, "code": "referral-capacity"}]},
        "method": {"coding": [{"system": MEASURE, "code": "referral-capacity"}]},
    }

    await _put(neo4j_driver, twice, None)

    assert [edges for _, _, edges in await _concept_links(neo4j_driver)] == [1]


# Round 2 (verifier hardening): a reference or a resource type must be a plain resource-type name
# and may not be a label another statement reads (the registry labels, the store's own labels).


@pytest.mark.parametrize(
    "target",
    [
        "Tenant/x",
        "TenantNumber/x",
        "Network/x",
        "NetworkMembership/x",
        "Grant/x",
        "Migration/x",
        "Concept/x",
        "Resource/x",
        "ResourceVersion/x",
        "organization/x",
        "Org_anisation/x",
        "Org-anisation/x",
        "Type1/x",
    ],
)
async def test_a_reference_to_a_registry_label_or_a_non_type_is_refused_and_writes_nothing(
    neo4j_driver: AsyncDriver, target: str
) -> None:
    with pytest.raises(ValidationFailed) as raised:
        await _put(neo4j_driver, {**_org(), "partOf": {"reference": target}}, None)
    assert target not in str(raised.value)
    with pytest.raises(ValidationFailed):
        await _put(
            neo4j_driver,
            {
                **_rich_service(),
                "coverageArea": [{"reference": "Location/ok"}, {"reference": target}],
            },
            None,
        )

    async def everything(tx: Any) -> int:
        record = await (
            await tx.run("MATCH (n) WHERE NOT n:Migration RETURN count(n) AS c")
        ).single()
        assert record is not None
        return int(record["c"])

    assert await read_tx(neo4j_driver, everything) == 0


@pytest.mark.parametrize("resource_type", ["Tenant", "TenantNumber", "Concept", "Network"])
async def test_a_resource_of_a_registry_type_is_refused_and_writes_nothing(
    neo4j_driver: AsyncDriver, resource_type: str
) -> None:
    with pytest.raises(ValidationFailed):
        await _put(neo4j_driver, {"resourceType": resource_type, "id": "x"}, None)
    assert await count_nodes(neo4j_driver, "Resource") == 0


async def test_a_reference_to_an_ordinary_type_is_still_accepted(neo4j_driver: AsyncDriver) -> None:
    await _put(neo4j_driver, {**_org(), "partOf": {"reference": "Organization/parent"}}, None)

    assert await _get(neo4j_driver, "Organization", ORG_ID) is not None
