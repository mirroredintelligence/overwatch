"""The scenarios of the resource store's statements (TEN-009, DEC-164, DEC-142 item 5).

One scenario per template of `resource_store.py`, run by the generated two-tenant test
(`tests/integration/graph_store/test_tenant_isolation.py`) with the label chain or relationship
type in `insert`. Both tenants get the same world with the same keys (the keys are composite with
the tenant, migration 0031), and the text that should differ is `Marked`, so a row or a change that
came from the wrong tenant looks different.

A resource, a backbone child, a version copy and a shared node are written by the store with the
tenant stamped, so the seeds below are stamped by the seeder the same way: `Resource` roots carry a
`key` and an `id`, children a `key` that starts with their root's key and `#`, shared nodes a key of
the form `Concept|system|code`. This module is pure data: no Neo4j, no tenant, no Cypher.
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

_ORG_KEY: Final = "Organization/org-1"
_OTHER_KEY: Final = "Organization/org-2"
_CHILD_KEY: Final = "Organization/org-1#address[0]"
_CONCEPT_KEY: Final = "Concept|sys|code-1"
_SYSTEM_KEY: Final = "CodeSystem|sys"
_PREFIX: Final = "Organization/org-1#"

_ORG: Final = SeedNode(
    "org",
    ("Resource", "Organization"),
    {"id": "org-1", "key": _ORG_KEY, "name": Marked("Org"), "versionId": "1"},
)
_OTHER: Final = SeedNode(
    "other",
    ("Resource", "Organization"),
    {"id": "org-2", "key": _OTHER_KEY, "name": Marked("Other"), "versionId": "1"},
)
_CHILD: Final = SeedNode("child", ("Address",), {"key": _CHILD_KEY, "city": Marked("Town")})
_CONCEPT: Final = SeedNode(
    "concept",
    ("Concept",),
    {"key": _CONCEPT_KEY, "system": "sys", "code": "code-1", "display": Marked("Shown")},
)
_BARE_CONCEPT: Final = SeedNode(
    "concept",
    ("Concept",),
    {"key": _CONCEPT_KEY, "system": "sys", "code": "code-1", "note": Marked("Bare")},
)
_SYSTEM: Final = SeedNode("system", ("CodeSystem",), {"key": _SYSTEM_KEY, "url": "sys"})
_VERSION: Final = SeedNode(
    "version",
    ("ResourceVersion",),
    {"key": "Organization/org-1@1", "id": "org-1", "name": Marked("Before"), "versionId": "1"},
)
_LOCATION: Final = SeedNode(
    "location",
    ("Resource", "Location"),
    {
        "id": "loc-1",
        "key": "Location/loc-1",
        "name": Marked("Site"),
        "positionLatitude": 50.5,
        "positionLongitude": -2.5,
    },
)

_ORG_SEED: Final = TenantSeed(nodes=(_ORG, _OTHER))
_TREE_SEED: Final = TenantSeed(nodes=(_ORG, _CHILD), rels=(SeedRel("org", "HAS_ADDRESS", "child"),))

_ROOT_OF_ORG: Final = {"resourceKey": _ORG_KEY, "key": _ORG_KEY}
_TREE_ROWS: Final = (
    {"props": {"name": Marked("Org"), "key": _ORG_KEY}},
    {"props": {"city": Marked("Town"), "key": _CHILD_KEY}},
)

SCENARIOS: Final[dict[str, Scenario]] = {
    "Q-RES-LOCK": Scenario(
        "lock the tenant's resource and stamp it",
        seed=_ORG_SEED,
        params={"key": _ORG_KEY, "id": "org-1", "stamp": "stamp-new"},
        lookup=("key", "id"),
        new=("stamp",),
        expect=Expect(
            rows=({"locked": 1},),
            after=(NodeSpec(("Organization",), {"id": "org-1", "lockStamp": "stamp-new"}),),
        ),
        insert=":Organization",
    ),
    "Q-RES-GET": Scenario(
        "read the tenant's resource root by key and type",
        seed=_ORG_SEED,
        params={"key": _ORG_KEY, "type": "Organization"},
        lookup=("key",),
        new=("type",),
        expect=Expect(rows=({"props": {"name": Marked("Org"), "id": "org-1", "versionId": "1"}},)),
    ),
    "Q-RES-UPSERT-ROOT": Scenario(
        "replace the properties of the tenant's resource root",
        seed=_ORG_SEED,
        params={
            "rows": [
                {
                    "key": _ORG_KEY,
                    "props": {"key": _ORG_KEY, "id": "org-1", "name": "Renamed", "versionId": "2"},
                }
            ]
        },
        new=("rows",),
        expect=Expect(
            rows=({"written": 1},),
            after=(NodeSpec(("Resource", "Organization"), {"name": "Renamed", "versionId": "2"}),),
        ),
        insert=":Resource:Organization",
    ),
    "Q-RES-UPSERT-NODE": Scenario(
        "replace the properties of the tenant's backbone child",
        seed=_TREE_SEED,
        params={
            "rows": [
                {"key": _CHILD_KEY, "props": {"key": _CHILD_KEY, "city": "Newtown"}},
            ]
        },
        new=("rows",),
        expect=Expect(
            rows=({"written": 1},),
            after=(NodeSpec(("Address",), {"city": "Newtown"}),),
        ),
        insert=":Address",
    ),
    "Q-RES-SHARED-READ": Scenario(
        "read the tenant's own shared nodes by key",
        seed=TenantSeed(nodes=(_CONCEPT, _SYSTEM)),
        params={"keys": [_CONCEPT_KEY, _SYSTEM_KEY]},
        expect=Expect(
            rows=(
                {"key": _CONCEPT_KEY, "props": {"display": Marked("Shown")}},
                {"key": _SYSTEM_KEY, "props": {"url": "sys"}},
            )
        ),
    ),
    "Q-RES-SHARED-CREATE": Scenario(
        "create the tenant's shared concepts that are missing and leave the others",
        seed=TenantSeed(nodes=(_CONCEPT,)),
        params={
            "rows": [
                {"key": _CONCEPT_KEY, "props": {"key": _CONCEPT_KEY, "system": "sys"}},
                {
                    "key": "Concept|sys|code-2",
                    "props": {"key": "Concept|sys|code-2", "system": "sys", "code": "code-2"},
                },
            ]
        },
        new=("rows",),
        expect=Expect(
            rows=({"written": 2},),
            nodes={"Concept": 1},
            after=(NodeSpec(("Concept",), {"code": "code-2"}),),
        ),
        insert=":Concept",
    ),
    "Q-RES-SHARED-FILL": Scenario(
        "fill a missing display of the tenant's own shared concept",
        seed=TenantSeed(nodes=(_BARE_CONCEPT,)),
        params={"key": _CONCEPT_KEY, "fill": {"display": "Filled"}},
        lookup=("key",),
        new=("fill",),
        expect=Expect(
            rows=({"filled": 1},),
            after=(NodeSpec(("Concept",), {"display": "Filled", "note": Marked("Bare")}),),
        ),
    ),
    "Q-RES-MERGE-NODES": Scenario(
        "create a placeholder for a reference target that does not exist yet",
        seed=_ORG_SEED,
        params={"rows": [{"key": "Location/loc-9", "id": "loc-9"}]},
        new=("rows",),
        expect=Expect(
            rows=({"written": 1},),
            nodes={"Resource": 1, "Location": 1},
            after=(NodeSpec(("Resource", "Location"), {"id": "loc-9", "placeholder": True}),),
        ),
        insert=":Location",
    ),
    "Q-RES-CLEAR-OWNED": Scenario(
        "delete the backbone children of the tenant's resource",
        seed=_TREE_SEED,
        params={"key": _ORG_KEY, "prefix": _PREFIX},
        lookup=("key",),
        new=("prefix",),
        expect=Expect(
            rows=({"cleared": 1},),
            nodes={"Address": -1},
            rels={"HAS_ADDRESS": -1},
            gone=(NodeSpec(("Address",), {"city": Marked("Town")}),),
        ),
    ),
    "Q-RES-CLEAR-ROOT-RELS": Scenario(
        "delete the outgoing relationships of the tenant's resource but its versions",
        seed=_TREE_SEED,
        params={"key": _ORG_KEY},
        lookup=("key",),
        expect=Expect(rows=({"cleared": 1},), rels={"HAS_ADDRESS": -1}),
    ),
    "Q-RES-MERGE-RELS": Scenario(
        "create a relationship between two of the tenant's nodes",
        seed=_ORG_SEED,
        params={
            "rows": [
                {"start": _ORG_KEY, "end": _OTHER_KEY, "props": {"fhirPath": "Organization.partOf"}}
            ]
        },
        new=("rows",),
        expect=Expect(rows=({"created": 1},), rels={"PART_OF": 1}),
        insert=":PART_OF",
    ),
    "Q-RES-LINK-SHARED": Scenario(
        "link the tenant's concept to its code system once",
        seed=TenantSeed(nodes=(_CONCEPT, _SYSTEM)),
        params={"rows": [{"start": _CONCEPT_KEY, "end": _SYSTEM_KEY}]},
        expect=Expect(rows=({"linked": 1},), rels={"IN_SYSTEM": 1}),
        insert=":IN_SYSTEM",
    ),
    "Q-RES-SET-POSITION": Scenario(
        "set the point of the tenant's location from its coordinates",
        seed=TenantSeed(nodes=(_LOCATION,)),
        params={"key": "Location/loc-1"},
        lookup=("key",),
        expect=Expect(
            rows=({"positioned": 1},),
            after=(NodeSpec(("Location",), {"name": Marked("Site")}),),
        ),
    ),
    "Q-RES-LOAD-NODES": Scenario(
        "load the tenant's resource root and its backbone children",
        seed=_TREE_SEED,
        params={**_ROOT_OF_ORG, "prefix": _PREFIX},
        lookup=("resourceKey", "key"),
        new=("prefix",),
        expect=Expect(rows=_TREE_ROWS),
        insert=":Resource",
    ),
    "Q-RES-LOAD-RELS": Scenario(
        "load the relationships of the tenant's resource and its children",
        seed=TenantSeed(
            nodes=(_ORG, _CHILD, _OTHER),
            rels=(SeedRel("org", "HAS_ADDRESS", "child"), SeedRel("org", "PART_OF", "other")),
        ),
        params={**_ROOT_OF_ORG, "prefix": _PREFIX},
        lookup=("resourceKey", "key"),
        new=("prefix",),
        expect=Expect(
            rows=(
                {"start": _ORG_KEY, "type": "HAS_ADDRESS", "end": _CHILD_KEY},
                {"start": _ORG_KEY, "type": "PART_OF", "end": _OTHER_KEY},
            )
        ),
        insert=":Resource",
    ),
    "Q-RES-HISTORY": Scenario(
        "list the versions of the tenant's resource",
        seed=TenantSeed(nodes=(_ORG, _VERSION), rels=(SeedRel("org", "HAS_VERSION", "version"),)),
        params={"key": _ORG_KEY},
        lookup=("key",),
        expect=Expect(rows=({"key": "Organization/org-1@1"},)),
    ),
}
