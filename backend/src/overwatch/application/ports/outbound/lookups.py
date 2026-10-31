"""Errors of the external reference lookups (I12): OS Places and the ODS directory.

A transient error (the service is down, busy or rate limited) says nothing about the request, so
the caller may try again later. A rejected request (refused for a reason a retry will not change)
is not retried. Messages are fixed texts: they never carry the key, the postcode or the code.
"""


class TransientLookupError(Exception):
    """A lookup that may succeed on retry: unreachable, busy, or a 5xx or 429 answer."""


class LookupRejected(Exception):
    """A lookup refused for a reason a retry will not change (a bad key, a bad request)."""
