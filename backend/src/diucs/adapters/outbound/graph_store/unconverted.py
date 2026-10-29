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
        "Q-BOOK-BY-REF",
        "Q-BOOK-CONFIRMED-FOR",
        "Q-BOOK-CONFIRMED-SINCE",
        "Q-BOOK-OPEN-FOR",
        "Q-BOOK-PENDING",
        "Q-BOOK-SET-PROPS",
        "Q-CAP-LATEST",
        "Q-CAP-LATEST-CONFIRMED-AT",
        "Q-CAP-LATEST-FOR",
        "Q-CAP-LOCK-SERVICE",
        "Q-CAP-SINCE",
        "Q-CAP-TRAILING-CONFIRMS",
        "Q-CASE-BY-REF",
        "Q-CASE-READ-POSTCODE",
        "Q-CASE-SET-POSTCODE",
        "Q-CASE-SET-REFERENCE",
        "Q-COMM-ADD",
        "Q-COMM-BY-PROVIDER",
        "Q-COMM-EXISTS",
        "Q-COMM-GET",
        "Q-COMM-LATEST-PROMPT",
        "Q-COMM-LINK-ABOUT",
        "Q-COMM-LINK-RECIPIENT",
        "Q-COMM-LINK-REPLY",
        "Q-COMM-SET-STATUS",
        "Q-CONTACT-GET",
        "Q-CONTACT-PUT",
        "Q-CRIT-CLEAR-CURRENT",
        "Q-CRIT-CURRENT",
        "Q-CRIT-CURRENT-FOR",
        "Q-CRIT-LABEL",
        "Q-CRIT-LOCK-SERVICE",
        "Q-CRIT-SET-CURRENT",
        "Q-CRIT-SUBJECT",
        "Q-CRIT-VERSIONS",
        "Q-DEVICE-KNOWN",
        "Q-DEVICE-LOCK",
        "Q-DEVICE-OWNER",
        "Q-DEVICE-REGISTER",
        "Q-DEVICE-REVOKE",
        "Q-FLAG-BASIC-STATE",
        "Q-FLAG-LABEL",
        "Q-FLAG-OBS-LOCK",
        "Q-FLAG-OBS-SERVICE",
        "Q-FLAG-REPORT-ADD",
        "Q-FLAG-REPORT-EXISTS",
        "Q-FLAG-REPORT-GET",
        "Q-FLAG-REPORT-LOCK",
        "Q-FLAG-REPORT-OPEN",
        "Q-FLAG-REPORT-SAVE",
        "Q-FLAG-SERVICE-ACTIVE",
        "Q-FLAG-SERVICE-LOCK",
        "Q-FLAG-SERVICES-WITH",
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
        "Q-SVC-LAST-REPORT",
        "Q-SVC-LIST-ACTIVE",
        "Q-WORK-ADD",
        "Q-WORK-FOR-ABOUT",
        "Q-WORK-GET",
        "Q-WORK-SAVE",
    }
)
