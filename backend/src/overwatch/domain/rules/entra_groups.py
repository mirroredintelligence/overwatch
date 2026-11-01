"""The Entra groups Overwatch creates in an organisation's own directory (DEC-1317).

Pure: no I/O. After the organisation's administrator has consented (DEC-1316), the platform
operator has Overwatch create one security group for the tenant's administrators and one for each
role it maps. Their names are fixed here, never typed:

- the prefix is `<ods>_overwatch_`, where `<ods>` is the tenant's ODS code, or the tenant id when it
  has none;
- the tenant-administrator group is `<prefix>tenant-admin`; a role's is `<prefix><role slug>`, the
  slug being the role's own code (`lead`, `clinical`, ...).

A name that is not built from the prefix is refused before any call. The tenant administrator's
later changes to membership are limited to groups whose names start with the prefix: this module
holds the check, and the use case asks it of the name the directory reports for a group Overwatch
mapped, never of text the client sent.

Members are never stored. The only things kept about a person are a keyed hash of the address (to
match it again) and a keyed hash of the directory object id.
"""

import hashlib
import hmac
import re
from typing import Final

from overwatch.domain.codes import Role
from overwatch.domain.errors import ValidationFailed
from overwatch.domain.model.tenant_records import ENTRA_MAPPABLE_ROLES

# The app role our staff app declares in its registration (display name "Overwatch member", value
# `Overwatch.Member`). It is declared in Azure, on app registration
# 7fb43bde-6a6d-4aed-9cac-9118de48ab52 (App roles); the id is copied here, not read from Azure, and
# a test pins the copy. Each role group is assigned to this app role on the organisation's copy of
# our service principal, so that the sign-in token's `groups` claim (groupMembershipClaims =
# ApplicationGroup) lists only these groups.
OVERWATCH_MEMBER_APP_ROLE_ID: Final = "52475a88-b5cd-4e30-9090-316d1c29672f"
OVERWATCH_MEMBER_APP_ROLE_VALUE: Final = "Overwatch.Member"

GROUP_INFIX: Final = "_overwatch_"
TENANT_ADMIN_SLUG: Final = Role.TENANT_ADMIN.value
NAME_MAX: Final = 120
"""Entra allows 256; ours are short, and a long ODS or tenant id is refused rather than cut."""

# What the operator may ask a role group for: every role a directory group may give, except the
# network administrator (its own flow, `MapNetworkAdminGroup`). The administrator group is always
# made and is not in this set.
OPERATOR_GROUP_ROLES: Final = ENTRA_MAPPABLE_ROLES - {Role.NETWORK_ADMIN, Role.TENANT_ADMIN}

_PREFIX_PART: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{0,63}")
_NAME: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,119}")
_HASH_DOMAIN_USER: Final = b"entra-group-user\x00"

REFUSED_NAME: Final = "that group name is not one Overwatch manages"
REFUSED_ROLE: Final = "that role does not have a group"


def group_prefix(ods_code: str | None, tenant_id: str) -> str:
    """`<ods>_overwatch_`: the ODS code when the tenant has one, else its id."""
    part = ods_code if ods_code else tenant_id
    if type(part) is not str or _PREFIX_PART.fullmatch(part) is None:
        raise ValidationFailed("tenant_id", "not usable in a group name")
    return f"{part}{GROUP_INFIX}"


def role_slug(role: Role) -> str:
    if type(role) is not Role or (
        role is not Role.TENANT_ADMIN and role not in OPERATOR_GROUP_ROLES
    ):
        raise ValidationFailed("role", REFUSED_ROLE)
    return role.value


def group_name(prefix: str, role: Role) -> str:
    """The fixed name of the group for a role, built from the prefix."""
    name = f"{prefix}{role_slug(role)}"
    return require_managed_name(name, prefix)


def is_managed_name(name: object, prefix: str) -> bool:
    return (
        type(name) is str
        and name.startswith(prefix)
        and len(name) > len(prefix)
        and len(name) <= NAME_MAX
        and _NAME.fullmatch(name) is not None
    )


def require_managed_name(name: object, prefix: str) -> str:
    """The name when it starts with the prefix and is plain; else a refusal that echoes nothing."""
    if not is_managed_name(name, prefix):
        raise ValidationFailed("group", REFUSED_NAME)
    assert type(name) is str
    return name


def role_of_name(name: str, prefix: str) -> Role | None:
    """The role a managed name stands for, or None when the suffix is not a role slug."""
    if not is_managed_name(name, prefix):
        return None
    suffix = name[len(prefix) :]
    for role in (Role.TENANT_ADMIN, *OPERATOR_GROUP_ROLES):
        if role.value == suffix:
            return role
    return None


def hash_user_ref(object_id: str, secret: bytes) -> str:
    """HMAC-SHA256 of a directory user's object id under the platform secret, in hex. The id is not
    the address, but it names a person, so only the hash is kept."""
    message = _HASH_DOMAIN_USER + object_id.lower().encode("ascii", "replace")
    return hmac.new(secret, message, hashlib.sha256).hexdigest()
