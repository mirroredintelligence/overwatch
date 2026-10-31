"""Key names for the identity stores (I13): every key carries the tenant bound to the unit of work.

Redis keys take the prefix `diucs:<tenant>:` (DEC-130, DEC-131). The tenant comes only from the
bound scope, never from an argument. A missing tenant is an error, never a default.
"""

from datetime import timedelta

from diucs.application.tenancy import current_tenant


def tenant_prefix(key_prefix: str) -> str:
    """The prefix of every key the bound tenant owns, e.g. `diucs:tenant-a:`. Raises TenantNotBound
    when no tenant is bound or a network scope is bound."""
    return f"{key_prefix}{current_tenant()}:"


def millis(ttl: timedelta) -> int:
    """A duration in whole milliseconds, rounded to the nearest, never below 1 (Redis refuses 0)."""
    return max(1, round(ttl / timedelta(milliseconds=1)))
