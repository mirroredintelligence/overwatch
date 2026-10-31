"""The one mapping from a secret reference to the name a store keeps it under (DEC-1304 item 2).

A secret is referred to as `<kind>/<tenant>/<name>` (`twilio/tenant-a/auth-token`) or by a platform
name with no slash (`bff-jwt`). Key Vault names allow only letters, digits and hyphens (1 to 127),
so
a slash becomes two hyphens: `twilio--tenant-a--auth-token`. One hyphen would collide
(`twilio/a-b/c` and `twilio/a/b-c` would both be `twilio-a-b-c`). The mapping is one-to-one because
only names built of lower-case letters and digits in parts joined by single hyphens, and parts
joined by `/`, are accepted: a part holds no `--` and does not begin or end with a hyphen, so `--`
in the result is always a slash. Anything else has no name (None): a store treats that as not
found and never looks anything up. The development file store uses the same names for its files, so
a name that works on a laptop works in the vault.

Pure: standard library only.
"""

import re
from typing import Final

MAX_VAULT_NAME_LENGTH: Final = 127

_PART: Final = r"[a-z0-9]+(?:-[a-z0-9]+)*"
_REFERENCE: Final = re.compile(rf"{_PART}(?:/{_PART})*")


def vault_secret_name(name: str) -> str | None:
    """The store name of a secret reference, or None when the reference has none (an empty or
    mis-shaped one, a character outside `[a-z0-9-/]`, `--`, a hyphen at the edge of a part, a name
    that is not text, or a result over 127 characters). Never raises."""
    if type(name) is not str or _REFERENCE.fullmatch(name) is None:
        return None
    mapped = name.replace("/", "--")
    if len(mapped) > MAX_VAULT_NAME_LENGTH:
        return None
    return mapped
