"""CreateTenant and the NHS record (DEC-1314): the tenant's own Organization is written into its own
scope, only for an NHS organisation, only with the record's own code, and rewrites the same node.

No Neo4j: the fakes of `tests/support/provisioning_fakes` record each bundle with the scope it was
written to. What the store holds is in the integration tests (not run in this build without Neo4j).
"""

from dataclasses import replace
from typing import Any

import pytest

from overwatch.application.tenancy import ScopeId
from overwatch.application.use_cases.tenant_admin import CreateTenant, CreateTenantCommand
from overwatch.domain.errors import ValidationFailed
from overwatch.domain.model.ods_record import OdsLink, OdsOrganisationRecord, OdsRole
from overwatch.domain.model.tenant import OrganisationType
from tests.support.provisioning_fakes import (
    NOW,
    TENANT,
    FakeHeads,
    FakePlatform,
    FakeWorld,
    FixedNow,
    operator,
)
from tests.support.tenancy import as_tenant

ODS = "F81044"
RECORD = OdsOrganisationRecord(
    code=ODS,
    name="THE ARDLEIGH SURGERY",
    status="Active",
    postcode="CO7 7LD",
    primary_role="RO177",
    roles=(OdsRole("RO177", "PRESCRIBING COST CENTRE", True),),
    links=(OdsLink("F81045", "A PARENT PRACTICE", "RO98"),),
    last_changed_at="2024-05-01",
)


def _create(platform: FakePlatform, world: FakeWorld, heads: FakeHeads) -> CreateTenant:
    return CreateTenant(platform, platform, heads, world.factory(), FixedNow())  # type: ignore[arg-type]


def _command(**fields: Any) -> CreateTenantCommand:
    base: dict[str, Any] = {
        "actor": operator(),
        "tenant_id": TENANT,
        "display_name": "The Ardleigh Surgery",
        "legal_name": "The Ardleigh Surgery",
        "organisation_type": OrganisationType.GP_PRACTICE,
        "ods_code": ODS,
    }
    return CreateTenantCommand(**{**base, **fields})


def _organisation_writes(world: FakeWorld) -> list[tuple[ScopeId | None, dict[str, Any]]]:
    return [
        (scope, bundle)
        for scope, bundle in world.bundles
        if bundle["entry"][0]["resource"]["resourceType"] == "Organization"
    ]


async def test_an_nhs_tenant_gets_its_organisation_in_its_own_scope_from_the_record() -> None:
    platform, world, heads = FakePlatform(), FakeWorld(), FakeHeads()

    with as_tenant(TENANT):
        await _create(platform, world, heads).execute(_command(ods_record=RECORD))

    ((scope, bundle),) = _organisation_writes(world)
    assert scope is not None and scope.value == TENANT
    (entry,) = bundle["entry"]
    assert entry["request"] == {"method": "PUT", "url": f"Organization/{ODS}"}
    assert entry["resource"]["name"] == "THE ARDLEIGH SURGERY"
    assert entry["resource"]["active"] is True
    assert entry["resource"]["extension"][0]["valueDateTime"] == NOW.strftime("%Y-%m-%dT%H:%M:%SZ")


async def test_an_nhs_tenant_without_a_record_still_carries_its_code_and_name() -> None:
    platform, world, heads = FakePlatform(), FakeWorld(), FakeHeads()

    with as_tenant(TENANT):
        await _create(platform, world, heads).execute(_command())

    ((_, bundle),) = _organisation_writes(world)
    resource = bundle["entry"][0]["resource"]
    assert resource["identifier"][0]["value"] == ODS
    assert resource["name"] == "The Ardleigh Surgery"
    assert "active" not in resource and "extension" not in resource


async def test_a_tenant_that_is_not_nhs_gets_no_organisation() -> None:
    platform, world, heads = FakePlatform(), FakeWorld(), FakeHeads()

    with as_tenant(TENANT):
        await _create(platform, world, heads).execute(
            _command(organisation_type=OrganisationType.OTHER, ods_code=None)
        )

    assert _organisation_writes(world) == []


async def test_a_record_for_a_tenant_that_is_not_nhs_is_refused_and_nothing_is_written() -> None:
    platform, world, heads = FakePlatform(), FakeWorld(), FakeHeads()

    with as_tenant(TENANT), pytest.raises(ValidationFailed) as refused:
        await _create(platform, world, heads).execute(
            _command(organisation_type=OrganisationType.OTHER, ods_code=None, ods_record=RECORD)
        )

    assert refused.value.field == "odsRecord"
    assert platform.calls == [] and world.bundles == []


async def test_a_record_of_another_code_than_the_tenant_is_refused_and_nothing_is_written() -> None:
    platform, world, heads = FakePlatform(), FakeWorld(), FakeHeads()
    other = replace(RECORD, code="F81045")

    with as_tenant(TENANT), pytest.raises(ValidationFailed):
        await _create(platform, world, heads).execute(_command(ods_record=other))

    assert platform.calls == [] and world.bundles == []


async def test_running_the_creation_again_writes_the_same_organisation_again_not_a_second_one() -> (
    None
):
    platform, world, heads = FakePlatform(), FakeWorld(), FakeHeads()

    with as_tenant(TENANT):
        first = await _create(platform, world, heads).execute(_command(ods_record=RECORD))
        again = await _create(platform, world, heads).execute(_command(ods_record=RECORD))

    assert first.created is True and again.created is False
    writes = _organisation_writes(world)
    assert len(writes) == 2
    assert {bundle["entry"][0]["request"]["url"] for _, bundle in writes} == {f"Organization/{ODS}"}
