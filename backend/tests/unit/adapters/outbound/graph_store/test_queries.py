import pytest

from diucs.adapters.outbound.graph_store.queries import REGISTRY, NamedQuery, QueryRegistry


def test_registered_query_is_returned_by_id() -> None:
    registry = QueryRegistry()
    query = NamedQuery(id="Q-SVC-LATEST", cypher="RETURN 1", mode="read")
    registry.register(query)
    assert registry.get("Q-SVC-LATEST") == query
    assert registry.ids() == ["Q-SVC-LATEST"]


def test_duplicate_query_id_is_a_value_error() -> None:
    registry = QueryRegistry()
    registry.register(NamedQuery(id="Q-DUP", cypher="RETURN 1", mode="read"))
    with pytest.raises(ValueError, match="Q-DUP"):
        registry.register(NamedQuery(id="Q-DUP", cypher="RETURN 2", mode="write"))


def test_unknown_query_id_is_a_key_error_naming_the_id() -> None:
    registry = QueryRegistry()
    with pytest.raises(KeyError, match="Q-UNKNOWN"):
        registry.get("Q-UNKNOWN")


def test_the_module_registry_starts_empty_of_test_queries() -> None:
    assert "Q-UNKNOWN" not in REGISTRY.ids()
    with pytest.raises(KeyError, match="Q-UNKNOWN"):
        REGISTRY.get("Q-UNKNOWN")


@pytest.mark.parametrize("mode", ["read", "write"])
def test_both_modes_are_accepted(mode: str) -> None:
    query = NamedQuery(id=f"Q-MODE-{mode}", cypher="RETURN 1", mode=mode)  # type: ignore[arg-type]
    assert query.mode == mode


@pytest.mark.parametrize("mode", ["", "READ", "delete"])
def test_any_other_mode_is_rejected(mode: str) -> None:
    with pytest.raises(ValueError, match="mode"):
        NamedQuery(id="Q-BAD-MODE", cypher="RETURN 1", mode=mode)  # type: ignore[arg-type]
