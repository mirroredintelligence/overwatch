"""The contract migration of the tenant schema (TEN-032, DEC-134 items 10 and 13, DEC-159 item 1).

One migration, id 0105 (the block 0105 to 0109 of TEN-032): it drops the eighteen superseded
single-property constraints, each with `IF EXISTS`, and nothing else. It refuses to run unless the
composite constraint that replaces each one exists (a precondition of the runner), so no key is
ever dropped without its replacement. The registry and global keys (`link_token_hash`,
`migration_id`, the `Tenant` and `TenantNumber` keys) are never touched.

The last test reads the final schema from the statements of every migration, in id order, and
checks the rule the whole task exists for: no unique key on a tenant label is single-property.
"""

import re
from collections.abc import Mapping

from diucs.adapters.outbound.graph_store.migration_types import Migration
from diucs.adapters.outbound.graph_store.migrations import MIGRATIONS
from diucs.adapters.outbound.graph_store.migrations_contract import (
    CONTRACT_MIGRATION_ID,
    CONTRACT_MIGRATIONS,
)
from diucs.adapters.outbound.graph_store.migrations_network import NETWORK_MIGRATIONS
from diucs.adapters.outbound.graph_store.migrations_platform import PLATFORM_MIGRATIONS
from diucs.adapters.outbound.graph_store.migrations_tenant import (
    COMPOSITE_CONSTRAINTS,
    REGISTRY_LABELS,
    SUPERSEDED_CONSTRAINTS,
    SUPERSEDED_INDEXES,
)

DROP = re.compile(r"DROP CONSTRAINT (\w+) IF EXISTS")
CREATE = re.compile(
    r"CREATE CONSTRAINT (\w+) IF NOT EXISTS FOR \(n:(\w+)\) REQUIRE (\(?[\w., ]+\)?) IS UNIQUE"
)


def test_the_contract_area_is_one_migration_with_the_id_of_the_block() -> None:
    assert CONTRACT_MIGRATION_ID == "0105_drop_superseded_keys"
    assert [m.id for m in CONTRACT_MIGRATIONS] == [CONTRACT_MIGRATION_ID]
    number = int(CONTRACT_MIGRATION_ID.split("_", 1)[0])
    assert 105 <= number <= 109


def test_it_is_assembled_after_every_other_migration() -> None:
    ids = [m.id for m in MIGRATIONS]
    assert ids.count(CONTRACT_MIGRATION_ID) == 1
    # Only the migrations of the network area, whose block starts at 0110 (build wave 5, bundle
    # W5E), and of the platform's own records (0190, wave 9 bundle W9C) follow it: they are expand
    # steps on labels that did not exist before, so they replace no key and need not wait for the
    # contract step.
    later = ids[ids.index(CONTRACT_MIGRATION_ID) + 1 :]
    assert later == [m.id for m in NETWORK_MIGRATIONS] + [m.id for m in PLATFORM_MIGRATIONS]
    assert all(int(i[:4]) >= 110 for i in later)


def test_it_has_only_drop_constraint_statements_with_if_exists_and_no_loop_or_parameter() -> None:
    (migration,) = CONTRACT_MIGRATIONS
    assert migration.loops == ()
    assert dict(migration.params) == {}
    assert migration.statements
    for statement in migration.statements:
        assert DROP.fullmatch(statement), statement


def test_it_drops_exactly_the_superseded_constraints_once_each() -> None:
    (migration,) = CONTRACT_MIGRATIONS
    dropped = [DROP.fullmatch(s).group(1) for s in migration.statements]  # type: ignore[union-attr]
    assert len(dropped) == len(set(dropped)) == 18
    assert set(dropped) == SUPERSEDED_CONSTRAINTS


def test_it_never_names_a_global_key_an_index_or_a_composite_key() -> None:
    (migration,) = CONTRACT_MIGRATIONS
    text = " ".join(migration.statements)
    for kept in (
        "link_token_hash",
        "migration_id",
        "tenant_id",
        "tenant_host",
        "tenant_entra_directory",
        "tenant_number_e164",
        "location_position",
    ):
        assert kept not in text, kept
    assert "INDEX" not in text
    assert not any(c.name in text.split() for c in COMPOSITE_CONSTRAINTS)
    assert not any(index in text.split() for index in SUPERSEDED_INDEXES)


def test_it_requires_the_composite_constraint_that_replaces_each_dropped_one() -> None:
    (migration,) = CONTRACT_MIGRATIONS
    replacement = {c.replaces: c.name for c in COMPOSITE_CONSTRAINTS if c.replaces is not None}
    assert set(replacement) == SUPERSEDED_CONSTRAINTS
    assert set(migration.requires) == set(replacement.values())
    assert len(migration.requires) == len(set(migration.requires)) == 18


def test_a_migration_requires_nothing_by_default() -> None:
    assert Migration("0090_a").requires == ()


def _final_unique_keys() -> Mapping[str, tuple[str, tuple[str, ...]]]:
    """name -> (label, properties) of every unique constraint after every migration, in order."""
    live: dict[str, tuple[str, tuple[str, ...]]] = {}
    for migration in MIGRATIONS:
        for statement in migration.statements:
            if (created := CREATE.fullmatch(statement)) is not None:
                name, label, props = created.groups()
                live[name] = (
                    label,
                    tuple(p.strip().removeprefix("n.") for p in props.strip("()").split(",")),
                )
            elif (dropped := DROP.fullmatch(statement)) is not None:
                live.pop(dropped.group(1), None)
    return live


def test_after_every_migration_no_unique_key_on_a_tenant_label_is_single_property() -> None:
    keys = _final_unique_keys()
    assert keys
    single = {
        name: label
        for name, (label, props) in keys.items()
        if label not in REGISTRY_LABELS and props[0] != "tenantId"
    }
    # The one global key on a tenant label: a link token is found by its hash with no scope.
    assert single == {"link_token_hash": "LinkToken"}


def test_after_every_migration_every_composite_key_of_a_tenant_leads_with_the_tenant() -> None:
    keys = _final_unique_keys()
    for name, (label, props) in keys.items():
        if label in REGISTRY_LABELS:
            continue
        if name == "link_token_hash":
            continue
        assert props[0] == "tenantId" and len(props) >= 2, name
    assert {c.name for c in COMPOSITE_CONSTRAINTS} <= set(keys)
    assert not SUPERSEDED_CONSTRAINTS & set(keys)
