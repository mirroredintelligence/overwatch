"""The scenarios of the criteria statements of `criteria_repository.py` (TEN-012, DEC-142 item 5).

One scenario per statement. The generated two-tenant test runs each one as tenant A and as tenant B
on a private container (DEC-150, DEC-159): both tenants get the same service, criteria versions and
links, with the same ids and keys, so a statement that forgets `tenantId: $tenant` finds the other
tenant's node by key. The text that should differ between the tenants is `Marked`.

The seeds are written the way the resource store writes them: a criteria version is a `Basic`
Resource whose `key` is `Basic/<id>`, its service is the `SUBJECT` of the Basic, and the service's
current version is its `CURRENT_CRITERIA` link. The `ServiceCriteria` label is set by the statement
that labels it (Q-CRIT-LABEL), so only the unlabelled seed carries no such label.

This module is pure data: no Neo4j, no tenant, no Cypher.
"""

from typing import Final

from diucs.adapters.outbound.graph_store.scenario import (
    Expect,
    Marked,
    NodeSpec,
    Scenario,
    SeedNode,
    SeedRel,
    TenantSeed,
)

_SERVICE_KEY: Final = "HealthcareService/svc-1"
_CURRENT_KEY: Final = "Basic/crit-1"
_NEXT_KEY: Final = "Basic/crit-2"

# svc-1 has one current version (crit-1) and a later draft (crit-2) that is not yet current.
_SERVICE: Final = SeedNode(
    "service",
    ("Resource", "HealthcareService"),
    {"id": "svc-1", "key": _SERVICE_KEY, "name": Marked("Ward"), "active": True},
)
_CURRENT: Final = SeedNode(
    "current",
    ("Resource", "Basic", "ServiceCriteria"),
    {
        "id": "crit-1",
        "key": _CURRENT_KEY,
        "status": "current",
        "version": 1,
        "ageMin": 0,
        "reviewBy": "2027-01-01",
        "changeReason": Marked("first"),
    },
)
_DRAFT: Final = SeedNode(
    "draft",
    ("Resource", "Basic", "ServiceCriteria"),
    {
        "id": "crit-2",
        "key": _NEXT_KEY,
        "status": "pending-approval",
        "version": 2,
        "ageMin": 0,
        "reviewBy": "2027-06-01",
        "changeReason": Marked("second"),
    },
)
_UNLABELLED: Final = SeedNode(
    "unlabelled",
    ("Resource", "Basic"),
    {
        "id": "crit-3",
        "key": "Basic/crit-3",
        "status": "draft",
        "version": 3,
        "ageMin": 0,
        "reviewBy": "2027-09-01",
        "changeReason": Marked("third"),
    },
)

_SEED: Final = TenantSeed(
    nodes=(_SERVICE, _CURRENT, _DRAFT),
    rels=(
        SeedRel("current", "SUBJECT", "service"),
        SeedRel("draft", "SUBJECT", "service"),
        SeedRel("service", "CURRENT_CRITERIA", "current"),
    ),
)
_UNLABELLED_SEED: Final = TenantSeed(
    nodes=(_SERVICE, _UNLABELLED),
    rels=(SeedRel("unlabelled", "SUBJECT", "service"),),
)

LOCK_SERVICE_SCENARIO: Final = Scenario(
    "lock the service of a criteria change",
    seed=_SEED,
    params={"serviceId": "svc-1"},
    lookup=("serviceId",),
    expect=Expect(rows=({"locked": 1},)),
)
LABEL_SCENARIO: Final = Scenario(
    "label an unlabelled criteria version as a service criteria",
    seed=_UNLABELLED_SEED,
    params={"key": "Basic/crit-3"},
    lookup=("key",),
    expect=Expect(
        rows=({"labelled": 1},),
        nodes={"ServiceCriteria": 1},
        after=(NodeSpec(("ServiceCriteria",), {"id": "crit-3"}),),
    ),
)
SUBJECT_SCENARIO: Final = Scenario(
    "read the service of a criteria version",
    seed=_SEED,
    params={"key": _CURRENT_KEY},
    lookup=("key",),
    expect=Expect(rows=({"serviceId": "svc-1"},)),
)
CURRENT_SCENARIO: Final = Scenario(
    "read the current criteria version of a service",
    seed=_SEED,
    params={"serviceId": "svc-1"},
    lookup=("serviceId",),
    expect=Expect(rows=({"id": "crit-1"},)),
)
# The services are a list, so the scenario has no lookup: the value is held by the seed, and the
# rows name the service they belong to.
CURRENT_FOR_SCENARIO: Final = Scenario(
    "read the current criteria version of each of some services",
    seed=_SEED,
    params={"serviceIds": ["svc-1"]},
    expect=Expect(rows=({"serviceId": "svc-1", "id": "crit-1"},)),
)
VERSIONS_SCENARIO: Final = Scenario(
    "list the versions of a service's criteria",
    seed=_SEED,
    params={"serviceId": "svc-1"},
    lookup=("serviceId",),
    expect=Expect(rows=({"id": "crit-2", "version": 2}, {"id": "crit-1", "version": 1})),
)
# Moves the service's current link from crit-1 to crit-2: one link goes, one comes, so the count
# of links does not change, and the row is the number of versions linked.
SET_CURRENT_SCENARIO: Final = Scenario(
    "make a criteria version the current one of its service",
    seed=_SEED,
    params={"serviceId": "svc-1", "key": _NEXT_KEY},
    lookup=("serviceId",),
    expect=Expect(rows=({"linked": 1},), rels={"CURRENT_CRITERIA": 0}),
)
CLEAR_CURRENT_SCENARIO: Final = Scenario(
    "take a criteria version off being the current one of its service",
    seed=_SEED,
    params={"serviceId": "svc-1", "key": _CURRENT_KEY},
    lookup=("serviceId",),
    expect=Expect(rows=({"cleared": 1},), rels={"CURRENT_CRITERIA": -1}),
)

CRITERIA_SCENARIOS: Final[dict[str, Scenario]] = {
    "Q-CRIT-LOCK-SERVICE": LOCK_SERVICE_SCENARIO,
    "Q-CRIT-LABEL": LABEL_SCENARIO,
    "Q-CRIT-SUBJECT": SUBJECT_SCENARIO,
    "Q-CRIT-CURRENT": CURRENT_SCENARIO,
    "Q-CRIT-CURRENT-FOR": CURRENT_FOR_SCENARIO,
    "Q-CRIT-VERSIONS": VERSIONS_SCENARIO,
    "Q-CRIT-SET-CURRENT": SET_CURRENT_SCENARIO,
    "Q-CRIT-CLEAR-CURRENT": CLEAR_CURRENT_SCENARIO,
}
