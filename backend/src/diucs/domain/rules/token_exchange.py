"""The pure rules of the token exchange (TEN-043, DEC-523 to DEC-526, DEC-134 item 2, DEC-136).

The back end issues the tenant-bound token after it has had the person's sign-in verified. What it
decides is here, with no I/O and no clock:

- a staff ROLE comes from the tenant's own role mapping and from nothing the identity token says:
  the groups the verified identity holds are looked up in the tenant's ACTIVE mappings, and the
  highest role among them wins (`staff_role`). A mapping that names a role that is not a staff role
  is ignored, so a damaged store cannot give a customer's group a platform role;
- an OPERATOR role comes from the app roles of the operator's own directory (`operator_role`);
- a directory counts as the tenant's only when its binding is VERIFIED (`directory_is_bound`);
- a token may be issued for a tenant by the one edge rule (`may_issue`): an active tenant, or a
  read-only suspended tenant for its administrator, so the exchange and the edge never disagree;
- a person at a tenant is a derived subject, and across tenants a derived account reference, both
  HMACs of the directory and the object id under a platform key (`staff_subject`, `account_ref`):
  an object id is unique only within its directory, so the same id in two directories is two
  people, and nothing shows the directory, the object id or the key.

Fail closed: a value of the wrong type is never a match. A refusal names a field and never a value.
"""

import base64
import hashlib
import hmac
import re
from collections.abc import Collection, Iterable
from datetime import UTC, datetime, timedelta
from typing import Final

from diucs.domain.codes import Role
from diucs.domain.errors import ValidationFailed
from diucs.domain.model.tenant import Tenant, check_tenant_id
from diucs.domain.model.tenant_records import (
    BindingStatus,
    EntraBinding,
    MappingStatus,
    RoleMapping,
)
from diucs.domain.rules.bff_token import EPOCH_MAX
from diucs.domain.rules.edge_access import EdgeVerdict, edge_verdict

# [ASSUMED] lifetimes. A staff session is a working shift (the BFF's own session lasted eight
# hours); an operator or a screen asks again within the hour. A suspend or a role change takes
# effect within a minute whatever the lifetime, through the epoch (DEC-250).
STAFF_TOKEN_LIFETIME: Final = timedelta(hours=8)
OPERATOR_TOKEN_LIFETIME: Final = timedelta(hours=1)
WALL_TOKEN_LIFETIME: Final = timedelta(hours=1)

# The staff roles, highest first. The two administration roles lead; a directory group cannot be
# mapped to them yet (ENTRA_MAPPABLE_ROLES), so they are reached only when provisioning allows it.
STAFF_ROLE_PRIORITY: Final = (
    Role.TENANT_ADMIN,
    Role.NETWORK_ADMIN,
    Role.LEAD,
    Role.CLINICAL,
    Role.ADVISOR,
    Role.OWNER,
    Role.EXEC,
    Role.AUDIT,
)
# The app roles of the operator's directory and the platform role each gives. A person who holds
# both is the platform operator, who has no data access (DEC-134 item 4).
OPERATOR_ROLE_CLAIMS: Final = {
    "DIUCS.PlatformOperator": Role.PLATFORM_OPERATOR,
    "DIUCS.Support": Role.SUPPORT,
}
_OPERATOR_PRIORITY: Final = (Role.PLATFORM_OPERATOR, Role.SUPPORT)

KEY_MIN_BYTES: Final = 32
_GUID: Final = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_SUBJECT_HEX: Final = 32


def staff_role(mappings: Iterable[RoleMapping], group_ids: Collection[str]) -> Role | None:
    """The highest staff role the tenant's ACTIVE mappings give for the groups held, or None."""
    held = {group.lower() for group in group_ids if type(group) is str}
    given: set[Role] = set()
    for mapping in mappings:
        if (
            type(mapping) is RoleMapping
            and mapping.status is MappingStatus.ACTIVE
            and mapping.group_object_id.lower() in held
        ):
            given.add(mapping.role)
    return next((role for role in STAFF_ROLE_PRIORITY if role in given), None)


def operator_role(app_roles: Collection[object]) -> Role | None:
    """The platform role the operator directory's app roles give, or None. An app role is matched
    exactly: a different case or a trailing space is another word."""
    held = {role for role in app_roles if type(role) is str}
    given = {OPERATOR_ROLE_CLAIMS[claim] for claim in held if claim in OPERATOR_ROLE_CLAIMS}
    return next((role for role in _OPERATOR_PRIORITY if role in given), None)


def directory_is_bound(bindings: Iterable[EntraBinding], directory_id: object) -> bool:
    """True when one of the tenant's bindings is for this directory and is VERIFIED. A pending or a
    revoked binding binds nothing."""
    if type(directory_id) is not str or _GUID.fullmatch(directory_id.lower()) is None:
        return False
    wanted = directory_id.lower()
    return any(
        type(binding) is EntraBinding
        and binding.status is BindingStatus.VERIFIED
        and binding.directory_id.lower() == wanted
        for binding in bindings
    )


def may_issue(tenant: object, role: object) -> bool:
    """Whether the back end may issue a token for this role on this tenant now: the edge's own rule
    asked about the tenant's current epoch, so a token it issues is one the edge would accept."""
    if type(tenant) is not Tenant or type(role) is not Role:
        return False
    if not 1 <= tenant.epoch <= EPOCH_MAX:
        return False
    verdict = edge_verdict(
        tenant, claimed_tenant=tenant.id, token_epoch=tenant.epoch, role=role, method="GET"
    )
    return verdict is EdgeVerdict.ALLOWED


def _key(key: object) -> bytes:
    if type(key) is not bytes or len(key) < KEY_MIN_BYTES:
        raise ValueError("the account key must be at least 32 bytes")
    return key


def _guid(field: str, value: object) -> str:
    if type(value) is not str or _GUID.fullmatch(value.lower()) is None:
        raise ValidationFailed(field, "must be a GUID")
    return value.lower()


def _mac(key: bytes, *parts: str) -> bytes:
    return hmac.new(key, "|".join(parts).encode("ascii"), hashlib.sha256).digest()


def account_ref(key: bytes, directory_id: str, object_id: str) -> str:
    """An opaque, stable reference to one person of one directory, the same in every tenant they
    work for (DEC-136 item 7: the only link between a person's accounts). 43 characters of
    base64url, the shape the network records take."""
    material = _mac(
        _key(key), "account", _guid("directory_id", directory_id), _guid("object_id", object_id)
    )
    return base64.urlsafe_b64encode(material).rstrip(b"=").decode("ascii")


def staff_subject(key: bytes, tenant_id: str, directory_id: str, object_id: str) -> str:
    """The token subject of one person at one tenant: `stf-` and 32 hex digits. Another tenant's
    subject for the same person is another value, so sessions and records are never shared."""
    check_tenant_id(tenant_id)
    material = _mac(
        _key(key),
        "subject",
        tenant_id,
        _guid("directory_id", directory_id),
        _guid("object_id", object_id),
    )
    return f"stf-{material.hex()[:_SUBJECT_HEX]}"


def expiry(now: datetime, lifetime: timedelta) -> datetime:
    """The instant a token issued at `now` ends: whole seconds, in UTC."""
    if not isinstance(now, datetime) or now.utcoffset() is None:
        raise ValidationFailed("now", "must be timezone-aware")
    return (now.astimezone(UTC) + lifetime).replace(microsecond=0)
