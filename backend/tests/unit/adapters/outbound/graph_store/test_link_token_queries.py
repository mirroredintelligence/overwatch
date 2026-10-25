"""The link-token queries are registered, and none of them takes the token text (P10).

Only the hash reaches the database. A query that took a `token` parameter could log or store it.
"""

import re

from diucs.adapters.outbound.graph_store import link_token_repository  # registers the queries
from diucs.adapters.outbound.graph_store.queries import REGISTRY

LINK_IDS = ["Q-LINK-ADD", "Q-LINK-GET", "Q-LINK-MARK-USED"]


def test_the_three_link_queries_are_registered() -> None:
    assert link_token_repository is not None
    for query_id in LINK_IDS:
        assert REGISTRY.get(query_id).id == query_id


def test_no_registered_link_query_has_a_token_parameter() -> None:
    link_ids = [query_id for query_id in REGISTRY.ids() if query_id.startswith("Q-LINK-")]
    assert sorted(link_ids) == sorted(LINK_IDS)
    for query_id in link_ids:
        assert not re.search(r"\$token(?!Hash)", REGISTRY.get(query_id).cypher), query_id


def test_mark_used_is_a_write_and_get_is_a_read() -> None:
    assert REGISTRY.get("Q-LINK-MARK-USED").mode == "write"
    assert REGISTRY.get("Q-LINK-GET").mode == "read"
