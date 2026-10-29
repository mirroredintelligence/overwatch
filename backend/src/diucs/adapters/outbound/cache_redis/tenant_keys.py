"""Key names for the identity stores (I13): every key carries the tenant bound to the unit of work.

Redis keys take the prefix `diucs:<tenant>:` (DEC-130, DEC-131). The tenant comes only from the
bound scope, never from an argument. A missing tenant is an error, never a default.
"""

from datetime import timedelta


def tenant_prefix(key_prefix: str) -> str:
    """The prefix of every key the bound tenant owns, e.g. `diucs:tenant-a:`."""
    raise NotImplementedError


def millis(ttl: timedelta) -> int:
    """A duration in whole milliseconds, rounded to the nearest, never less than 1."""
    raise NotImplementedError
