"""Writing a FHIR transaction bundle through the resource store (U27).

A bundle entry names its resource by `fullUrl` `urn:uuid:<id>`, and references to it elsewhere in
the bundle use that URL. The writer resolves each such reference to `<Type>/<id>`, then writes the
entries in the order given: a POST is a new resource (the store refuses an id that exists), and a
PUT replaces the stored one at its current version (a service placeholder, DEC-082 item 4). It
commits nothing: the caller's unit of work owns the transaction, so a failure anywhere leaves
nothing (DEC-012).

The resolution is pure and refuses a bundle that is not a transaction, an entry whose `fullUrl` is
not its own id, a method other than POST or PUT, a URL that names another resource, two entries with
one id, a reference to nothing in the bundle, and a resource that names a tenant: the tenant is
stamped by the store from the bound scope, never taken from a bundle (DEC-130).
"""

import copy
from dataclasses import dataclass
from typing import Any, Final, Protocol

from diucs.adapters.outbound.graph_store.extensions import TENANT_OWNED_NAMES
from diucs.domain.errors import NotFound, ValidationFailed

_URN: Final = "urn:uuid:"
_METHODS: Final = frozenset({"POST", "PUT"})


class _Store(Protocol):
    async def put(self, resource: dict[str, Any], expected_version: str | None) -> str: ...

    async def get(self, type: str, id: str) -> dict[str, Any] | None: ...


@dataclass(frozen=True, slots=True)
class BundleEntry:
    method: str
    type: str
    id: str
    full_url: str
    resource: dict[str, Any]


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValidationFailed(field, "must be text")
    return value


def _entries_of(bundle: object) -> list[dict[str, Any]]:
    if not isinstance(bundle, dict) or bundle.get("resourceType") != "Bundle":
        raise ValidationFailed("bundle", "must be a Bundle")
    if bundle.get("type") != "transaction":
        raise ValidationFailed("bundle", "must be a transaction bundle")
    entries = bundle.get("entry")
    if not isinstance(entries, list) or not entries:
        raise ValidationFailed("bundle", "must have at least one entry")
    if not all(isinstance(entry, dict) for entry in entries):
        raise ValidationFailed("entry", "must be an object")
    return entries


def _targets(entries: list[dict[str, Any]]) -> dict[str, str]:
    """Each entry's full URL against `<Type>/<id>`, after the entry's own checks."""
    targets: dict[str, str] = {}
    for entry in entries:
        resource = entry.get("resource")
        if not isinstance(resource, dict):
            raise ValidationFailed("entry", "must carry a resource")
        resource_type = _text(resource.get("resourceType"), "resourceType")
        resource_id = _text(resource.get("id"), "id")
        full_url = _text(entry.get("fullUrl"), "fullUrl")
        if full_url != f"{_URN}{resource_id}":
            raise ValidationFailed("fullUrl", "must be urn:uuid: and the id of the resource")
        if full_url in targets:
            raise ValidationFailed("fullUrl", "two entries have the same id")
        if TENANT_OWNED_NAMES & set(resource):
            raise ValidationFailed("resource", "a bundle cannot name a tenant")
        targets[full_url] = f"{resource_type}/{resource_id}"
    return targets


def _resolved(value: Any, targets: dict[str, str]) -> Any:
    if isinstance(value, dict):
        return {key: _reference(key, item, targets) for key, item in value.items()}
    if isinstance(value, list):
        return [_resolved(item, targets) for item in value]
    return value


def _reference(key: str, value: Any, targets: dict[str, str]) -> Any:
    if key == "reference" and isinstance(value, str) and value.startswith(_URN):
        target = targets.get(value)
        if target is None:
            raise ValidationFailed("reference", "names an entry that is not in the bundle")
        return target
    return _resolved(value, targets)


def resolve_bundle(bundle: dict[str, Any]) -> list[BundleEntry]:
    """The entries of a transaction bundle, in order, with every `urn:uuid:` reference resolved to
    `<Type>/<id>`. The bundle itself is not changed."""
    entries = _entries_of(bundle)
    targets = _targets(entries)
    resolved: list[BundleEntry] = []
    for entry in entries:
        resource = copy.deepcopy(entry["resource"])
        resource_type = str(resource["resourceType"])
        resource_id = str(resource["id"])
        request = entry.get("request")
        method = request.get("method") if isinstance(request, dict) else None
        if method not in _METHODS:
            raise ValidationFailed("request", "the method must be POST or PUT")
        url = request.get("url") if isinstance(request, dict) else None
        expected_url = resource_type if method == "POST" else f"{resource_type}/{resource_id}"
        if url != expected_url:
            raise ValidationFailed("request", "the url must name the resource")
        resolved.append(
            BundleEntry(
                method=str(method),
                type=resource_type,
                id=resource_id,
                full_url=str(entry["fullUrl"]),
                resource=_resolved(resource, targets),
            )
        )
    return resolved


async def write_bundle(store: _Store, bundle: dict[str, Any]) -> dict[str, str]:
    """Write every entry through the store, in order, and return each full URL against
    `<Type>/<id>`. A PUT for a resource that does not exist is NotFound, with the entries before it
    already written in the caller's transaction (which the caller rolls back)."""
    written: dict[str, str] = {}
    for entry in resolve_bundle(bundle):
        if entry.method == "POST":
            await store.put(entry.resource, None)
        else:
            current = await store.get(entry.type, entry.id)
            if current is None:
                raise NotFound(f"{entry.type} to replace")
            await store.put(entry.resource, str(current["meta"]["versionId"]))
        written[entry.full_url] = f"{entry.type}/{entry.id}"
    return written
