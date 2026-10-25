"""Integration tests for the graph writer and reader (G05, rule R10, DEC-053).

They run against the throwaway Neo4j that the F10 harness starts for the pytest session (DEC-008).
Every write goes through ResourceStore in one committed transaction, and every read happens in a
fresh session, so what the tests assert is what was really stored. All values are synthetic.
"""

import asyncio
import json
from datetime import UTC, datetime
from typing import Any

import pytest
from neo4j import AsyncDriver
from neo4j.spatial import WGS84Point
from neo4j.time import DateTime

from diucs.adapters.outbound.graph_store.resource_store import ResourceStore
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.domain.codes import BASE_URL
from diucs.domain.errors import Conflict, NotAllowed, ValidationFailed
from tests.support.neo4j import count_nodes, node_props, read_tx, write_tx
from tests.unit.adapters.outbound.graph_store.test_mapper_backbone import SVC_ID, UCR_WEST

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


async def test_a_replayed_create_with_the_same_key_returns_the_same_version(
    neo4j_driver: AsyncDriver,
) -> None:
    async def first(tx: Any) -> str:
        return await ResourceStore(tx, FixedClock(AT)).put(_org(), None, idempotency_key="k-create")

    async def replay(tx: Any) -> str:
        return await ResourceStore(tx, FixedClock(AT)).put(_org(), None, idempotency_key="k-create")

    assert await write_tx(neo4j_driver, first) == "1"
    assert await write_tx(neo4j_driver, replay) == "1"
    assert await count_nodes(neo4j_driver, "ResourceVersion") == 0
    assert await _get(neo4j_driver, "Organization", ORG_ID) == _with_meta(_org(), "1")


async def test_a_replayed_update_with_the_same_key_writes_no_second_version(
    neo4j_driver: AsyncDriver,
) -> None:
    await _put(neo4j_driver, _org("Before"), None)

    async def update(tx: Any) -> str:
        return await ResourceStore(tx, FixedClock(AT)).put(
            _org("After"), "1", idempotency_key="k-update"
        )

    assert await write_tx(neo4j_driver, update) == "2"
    assert await write_tx(neo4j_driver, update) == "2"
    assert await count_nodes(neo4j_driver, "ResourceVersion") == 1
    assert await _get(neo4j_driver, "Organization", ORG_ID) == _with_meta(_org("After"), "2")


async def test_a_key_reused_for_a_different_write_is_refused(neo4j_driver: AsyncDriver) -> None:
    async def first(tx: Any) -> str:
        return await ResourceStore(tx, FixedClock(AT)).put(_org("A"), None, idempotency_key="k-x")

    async def other(tx: Any) -> str:
        return await ResourceStore(tx, FixedClock(AT)).put(_org("B"), None, idempotency_key="k-x")

    assert await write_tx(neo4j_driver, first) == "1"
    with pytest.raises(Conflict):
        await write_tx(neo4j_driver, other)
    assert await _get(neo4j_driver, "Organization", ORG_ID) == _with_meta(_org("A"), "1")


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
