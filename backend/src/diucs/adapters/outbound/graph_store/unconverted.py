"""The ratchet (DEC-142 item 5): the statements that existed before the tenancy seam and have not
been converted yet. Each is a tenant statement that does not mention `$tenant`, has no `Scenario`,
or both.

The list may only shrink. A conversion bundle removes the ids of the statements it converts, in the
same commit that converts them, and lowers the number pinned in
`tests/unit/adapters/outbound/graph_store/test_queries.py`. A new statement is never added here: the
registry refuses a tenant statement that does not mention `$tenant` or has no scenario unless its id
is on this list. The templates of the resource store left the list in TEN-009 (DEC-164); an id of
a template would stand for every instance of it (`Q-X-Y` for `Q-X-Y:Resource:Organization`).

While an id is on this list its statement may run with no scope bound, as before the seam; when the
list is empty that exemption is removed from `run_query`.
"""

from typing import Final

UNCONVERTED: Final[frozenset[str]] = frozenset(
    {
        "Q-AUDIT-APPEND",
        "Q-AUDIT-CHAIN",
        "Q-AUDIT-ENSURE-HEAD",
        "Q-AUDIT-HEAD",
        "Q-AUDIT-LINK-AGENT",
        "Q-AUDIT-LINK-ENTITY",
        "Q-AUDIT-LIST",
        "Q-AUDIT-LOCK-HEAD",
        "Q-IDEM-CREATE",
        "Q-IDEM-EDGES",
        "Q-IDEM-HEAD",
        "Q-IDEM-LINK",
        "Q-IDEM-VALUES",
        "Q-OUTBOX-FAILED",
        "Q-OUTBOX-LOCK",
        "Q-OUTBOX-PUBLISHED",
        "Q-PROV-APPEND",
        "Q-PROV-LINK",
        "Q-PROV-SOURCE",
    }
)
