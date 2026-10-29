"""Pure tests of the protected text store (P20): handles, the length limit, the label guard over
the whole registry, and the statement shape. The Neo4j behaviour is in
tests/integration/graph_store/test_protected_text_store.py.
"""

import base64
import importlib
import pkgutil
import re
from typing import Any

import pytest

import diucs.adapters.outbound.graph_store as graph_store_package
from diucs.adapters.outbound.graph_store import protected_text_store
from diucs.adapters.outbound.graph_store.protected_text_store import (
    Neo4jProtectedTextStore,
    checked_text,
    new_handle,
)
from diucs.adapters.outbound.graph_store.queries import REGISTRY
from diucs.adapters.outbound.graph_store.scenario import validate_scenario
from diucs.adapters.outbound.graph_store.unconverted import UNCONVERTED
from diucs.domain.errors import ValidationFailed

PROTECTED_LABEL = re.compile(r":\s*`?Protected(?:Text)?`?\b")


def _load_every_module() -> None:
    for module in pkgutil.walk_packages(
        graph_store_package.__path__, f"{graph_store_package.__name__}."
    ):
        importlib.import_module(module.name)


def test_a_handle_is_a_url_safe_token_of_at_least_128_bits() -> None:
    handle = new_handle()

    assert len(handle) >= 22
    assert re.fullmatch(r"[A-Za-z0-9_-]+", handle)
    # 22 characters of base64url carry 128 bits or more: 16 bytes after decoding.
    padded = handle + "=" * (-len(handle) % 4)
    assert len(base64.urlsafe_b64decode(padded)) >= 16


def test_handles_do_not_repeat() -> None:
    assert len({new_handle() for _ in range(1000)}) == 1000


def test_text_of_280_characters_is_stored_as_it_is() -> None:
    text = "a" * 280

    assert checked_text(text) == text


def test_text_of_281_characters_is_refused() -> None:
    with pytest.raises(ValidationFailed) as refused:
        checked_text("a" * 281)

    assert refused.value.field == "text"
    assert "a" * 20 not in str(refused.value)


@pytest.mark.parametrize("text", ["", "   "])
def test_blank_text_is_refused(text: str) -> None:
    with pytest.raises(ValidationFailed):
        checked_text(text)


async def test_an_unknown_kind_is_refused_before_anything_is_written() -> None:
    store = Neo4jProtectedTextStore(tx=None)  # type: ignore[arg-type]

    with pytest.raises(ValidationFailed) as refused:
        await store.put("gossip", "task-1", "Board showed accepting")

    assert refused.value.field == "kind"


async def test_an_over_long_text_is_refused_before_anything_is_written() -> None:
    store = Neo4jProtectedTextStore(tx=None)  # type: ignore[arg-type]

    with pytest.raises(ValidationFailed):
        await store.put("safety-concern", "task-1", "a" * 281)


def test_only_protected_statements_name_the_protected_label() -> None:
    _load_every_module()
    for query_id in REGISTRY.ids():
        if query_id.startswith("Q-PROT-"):
            continue
        assert not PROTECTED_LABEL.search(REGISTRY.get(query_id).cypher), query_id


def test_the_protected_statements_are_registered_and_carry_scenarios() -> None:
    _load_every_module()
    ids = [q for q in REGISTRY.ids() if q.startswith("Q-PROT-")]
    assert {"Q-PROT-PUT", "Q-PROT-GET"} <= set(ids)
    pattern = re.compile(r"\((?:\w+)?(?::\w+)+\s*(\{[^}]*\})?\)")
    for query_id in ids:
        query = REGISTRY.get(query_id)
        for match in pattern.finditer(query.cypher):
            assert match.group(1) is not None and "tenantId: $tenant" in match.group(1), query_id
        assert query.scenario is not None, query_id
        assert validate_scenario(query_id, query.scenario) == [], query_id
        assert query_id not in UNCONVERTED


def test_a_protected_text_node_has_no_relationship_in_its_statement() -> None:
    _load_every_module()
    cypher: Any = REGISTRY.get("Q-PROT-PUT").cypher
    assert "-[" not in cypher
    assert "(p:Protected:ProtectedText" in cypher or "Protected:ProtectedText" in cypher


def test_the_protected_module_exposes_its_kinds() -> None:
    assert protected_text_store.KINDS == frozenset(
        {"safety-concern", "problem-report", "clinical-note"}
    )
