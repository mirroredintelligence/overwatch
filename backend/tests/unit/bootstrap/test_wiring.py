"""The composition of the registration use cases and the tenant's area (R11, U27, U28).

`SubmitRegistration` is built with the write of `PersistRegistration`, so a submit that succeeds
writes the registration's resources; and the review gets the area of the tenant from the settings,
with no default: a tenant with no area fails every address check (DEC-317).
"""

import pytest

from diucs.adapters.outbound.graph_store.connection import Neo4jConnection
from diucs.application.tenancy import ScopeId
from diucs.application.use_cases.registration_draft import SubmitRegistration
from diucs.application.use_cases.registration_submit import PersistRegistration
from diucs.bootstrap.areas import area_districts_for, parse_area
from diucs.bootstrap.container import build_for_tests
from diucs.bootstrap.settings import Settings
from diucs.bootstrap.wiring import submit_registration


def test_an_area_is_a_list_of_districts_and_runs() -> None:
    assert parse_area("DT1-DT3, BH7, dt10") == frozenset({"DT1", "DT2", "DT3", "BH7", "DT10"})


@pytest.mark.parametrize(
    "text",
    ["", "  ", "DT1-BH3", "DT3-DT1", "DT0-DT3", "DT", "DT4 8", "DT1-DT3-DT5", "D1-DT", "1-3"],
)
def test_an_area_that_is_not_districts_is_refused_when_the_settings_are_read(text: str) -> None:
    with pytest.raises(ValueError, match="area"):
        parse_area(text)


def test_each_tenant_has_its_own_area_and_a_tenant_with_none_has_none() -> None:
    areas = area_districts_for({"tenant-a": "DT1-DT2", "tenant-b": "BH1"})
    assert areas(ScopeId.tenant("tenant-a")) == frozenset({"DT1", "DT2"})
    assert areas(ScopeId.tenant("tenant-b")) == frozenset({"BH1"})
    assert areas(ScopeId.tenant("tenant-c")) == frozenset()


def test_a_network_scope_has_no_area() -> None:
    areas = area_districts_for({"tenant-a": "DT1"})
    assert areas(ScopeId.network("net-sample")) == frozenset()


def test_the_settings_carry_the_areas_and_default_to_none(monkeypatch: pytest.MonkeyPatch) -> None:
    assert Settings().tenant_areas == {}
    monkeypatch.setenv("DIUCS_TENANT_AREAS", '{"tenant-a": "DT1-DT11"}')
    assert Settings().tenant_areas == {"tenant-a": "DT1-DT11"}


async def test_the_container_supplies_the_area_of_the_tenant() -> None:
    connection = Neo4jConnection("bolt://localhost:1", "neo4j", "unused-without-a-session")
    try:
        container = build_for_tests(neo4j=connection, areas={"tenant-a": "DT1-DT2"})
        assert container.area_districts_for(ScopeId.tenant("tenant-a")) == frozenset({"DT1", "DT2"})
        assert (
            build_for_tests(neo4j=connection).area_districts_for(ScopeId.tenant("tenant-a"))
            == frozenset()
        )
    finally:
        await connection.close()


async def test_a_submit_built_by_the_composition_root_writes_the_registration() -> None:
    connection = Neo4jConnection("bolt://localhost:1", "neo4j", "unused-without-a-session")
    try:
        container = build_for_tests(neo4j=connection)
        submit = submit_registration(container)
        assert isinstance(submit, SubmitRegistration)
        assert isinstance(submit._persist, PersistRegistration)  # noqa: SLF001
    finally:
        await connection.close()
