"""The partition of node labels by the kind of scope that holds them (TEN-037, DEC-132 item 4).

A scope is a tenant or a network, and the two hold different nodes:

- `NETWORK_ONLY_LABELS`: what the projector writes into a network scope and a network read reads
  (the five labels of the projection allowlist, `domain/rules/projection.py`, and the two
  bookkeeping labels of a projection source and its cursor). A tenant scope never holds one.
- `SCOPE_GENERIC_LABELS`: platform nodes that are stamped with the scope and mean the same in
  either kind (the audit chain of the scope, the idempotency record, the processed marker).
- `REGISTRY_NODE_LABELS`: the registry nodes, which carry no scope at all (`REGISTRY_LABELS`).
- Every other label is a tenant's data (`HealthcareService`, `Observation`, `Patient`, ...).

The registration check of `queries.py` uses the partition so that a statement that runs in a tenant
scope cannot name a network or registry label, and a network statement cannot name a tenant's data:
a statement cannot write a projection from a tenant scope, or read private data from a network
scope, even if a scope were bound wrongly. This is a cheap check and not a proof: the proof is the
generated test over all three scopes (TEN-060). Pure: no import of the driver.
"""

from typing import Final

from diucs.adapters.outbound.graph_store.migrations_tenant import REGISTRY_LABELS

NETWORK_ONLY_LABELS: Final[frozenset[str]] = frozenset(
    {
        "ProjectedService",
        "ProjectedLocation",
        "ProjectedOpeningHour",
        "ProjectedCapacity",
        "ProjectedCriteria",
        "ProjectionSource",
        "ProjectionCursor",
    }
)

SCOPE_GENERIC_LABELS: Final[frozenset[str]] = frozenset(
    {
        "AuditHead",
        "AuditEvent",
        "ChainLink",
        "AuditRef",
        "Snapshot",
        "IdempotencyRecord",
        "IdempotencyValue",
        "Processed",
    }
)

REGISTRY_NODE_LABELS: Final[frozenset[str]] = frozenset(REGISTRY_LABELS)
