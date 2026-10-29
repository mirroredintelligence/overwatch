"""The actor carries the tenant it acts in (TEN-018, DEC-130 item 6).

`tenant_id` is required: an actor built without one is a TypeError, so nothing is built that does
not know its tenant. A value that is not a tenant id is refused with a fixed-form refusal that names
no value. The system, wall and anonymous actors are built for one tenant; there is no module
constant that holds one. Pure tests: no Neo4j.
"""

import dataclasses
from typing import Any

import pytest

from diucs.application.actor import Actor, anonymous_actor, system_actor, wall_actor
from diucs.application.tenancy import ScopeInvalid, bind_tenant, current_tenant
from diucs.domain.codes import Role
from diucs.domain.errors import ValidationFailed

TENANT = "tenant-a"
OTHER = "tenant-b"


def make(**changes: Any) -> Actor:
    fields: dict[str, Any] = {
        "role": Role.ADVISOR,
        "practitioner_id": "prac-1",
        "device_id": None,
        "channel": "api",
        "service_ids": frozenset({"svc-1"}),
        "tenant_id": TENANT,
    }
    fields.update(changes)
    return Actor(**fields)


def test_an_actor_holds_its_tenant() -> None:
    assert make().tenant_id == TENANT


def test_an_actor_without_a_tenant_cannot_be_built() -> None:
    with pytest.raises(TypeError):
        Actor(  # type: ignore[call-arg]
            role=Role.ADVISOR,
            practitioner_id="prac-1",
            device_id=None,
            channel="api",
            service_ids=frozenset(),
        )


def test_the_tenant_is_the_last_positional_field_so_the_first_five_keep_their_places() -> None:
    actor = Actor(Role.LEAD, "pr-1", None, "api", frozenset(), TENANT)

    assert (actor.role, actor.practitioner_id, actor.channel, actor.tenant_id) == (
        Role.LEAD,
        "pr-1",
        "api",
        TENANT,
    )


def test_two_actors_of_different_tenants_are_not_equal() -> None:
    assert make(tenant_id=TENANT) != make(tenant_id=OTHER)
    assert make(tenant_id=TENANT) == make(tenant_id=TENANT)


def test_the_actor_is_frozen() -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        make().tenant_id = OTHER  # type: ignore[misc]


@pytest.mark.parametrize(
    "tenant",
    [
        "",
        "t",
        "Tenant-A",
        "tenant a",
        "tenant:a",
        "tenant/a",
        "net-dorset",
        "platform",
        "t" * 32,
        "tenant-a\n",
    ],
)
def test_a_tenant_that_is_not_a_tenant_id_is_refused(tenant: str) -> None:
    with pytest.raises(ValidationFailed) as refused:
        make(tenant_id=tenant)

    assert tenant not in str(refused.value) or tenant == ""


@pytest.mark.parametrize("tenant", [None, 7, b"tenant-a", ["tenant-a"]])
def test_a_tenant_that_is_not_text_is_refused(tenant: object) -> None:
    with pytest.raises(ValidationFailed):
        make(tenant_id=tenant)


def test_the_default_tenant_is_a_tenant() -> None:
    assert make(tenant_id="default").tenant_id == "default"


def test_replace_runs_the_tenant_check_again() -> None:
    with pytest.raises(ValidationFailed):
        dataclasses.replace(make(), tenant_id="Not A Tenant")


# ---------------------------------------------------------------- built for one tenant


def test_a_wall_actor_is_a_wall_device_of_one_tenant() -> None:
    actor = wall_actor(TENANT)

    assert actor == Actor(
        role=Role.WALL,
        practitioner_id=None,
        device_id=None,
        channel="system",
        service_ids=frozenset(),
        tenant_id=TENANT,
    )


def test_a_wall_actor_can_name_its_device() -> None:
    actor = wall_actor(TENANT, device_id="dev-1")

    assert actor.device_id == "dev-1"
    assert actor.tenant_id == TENANT


def test_wall_actors_of_two_tenants_differ() -> None:
    assert wall_actor(TENANT) != wall_actor(OTHER)


def test_a_system_actor_is_the_owner_role_in_its_channel_and_tenant() -> None:
    actor = system_actor(TENANT, "scheduler")

    assert actor == Actor(
        role=Role.OWNER,
        practitioner_id=None,
        device_id=None,
        channel="scheduler",
        service_ids=frozenset(),
        tenant_id=TENANT,
    )


def test_an_anonymous_actor_has_the_anonymous_link_role() -> None:
    actor = anonymous_actor(TENANT, "text-code")

    assert actor.role is Role.ANONYMOUS_LINK
    assert actor.channel == "text-code"
    assert actor.practitioner_id is None
    assert actor.device_id is None
    assert actor.service_ids == frozenset()
    assert actor.tenant_id == TENANT


@pytest.mark.parametrize("build", [wall_actor, lambda tenant: system_actor(tenant, "scheduler")])
def test_the_built_actors_refuse_a_bad_tenant(build: Any) -> None:
    with pytest.raises(ValidationFailed):
        build("Not A Tenant")


def test_building_an_actor_does_not_bind_anything() -> None:
    wall_actor(TENANT)

    with pytest.raises(Exception, match="no tenant is bound"):
        current_tenant()


def test_an_actor_of_another_tenant_does_not_change_the_binding() -> None:
    with bind_tenant(OTHER):
        make(tenant_id=TENANT)
        assert current_tenant() == OTHER


def test_the_scope_invalid_error_is_not_what_an_actor_raises() -> None:
    # The actor uses the domain's rule, which also refuses the reserved platform id.
    with pytest.raises(ValidationFailed):
        make(tenant_id="platform")
    assert not issubclass(ValidationFailed, ScopeInvalid)
