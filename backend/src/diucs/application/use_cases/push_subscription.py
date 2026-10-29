"""SavePushSubscription and RemovePushSubscription (I14): a reporter's or exec's installed app
subscribes to Web Push, and unsubscribes.

Saving records the subscription (P19) and the notification consent (the consent screen came first,
the app asks for permission after it) in the same unit of work as the audit entry and the replay
record. The subscription JSON is never in the audit, a log or an error: the audit records the device
id and the wording version only.

The practitioner is always the actor's own. A device of another practitioner reads as NotFound.
Replays use the tenant-scoped key of the command (lesson L160): the same key in another tenant is a
different command.
"""

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final

from diucs.application.actor import Actor
from diucs.application.idempotency import IdempotencyStore
from diucs.application.ports.outbound.audit import AuditEntry
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.ids import IdGenerator
from diucs.application.ports.outbound.messaging import PushSubscription
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.tenancy import ScopeId, ScopeKind, TenantNotBound, current_scope
from diucs.domain.errors import Conflict, NotAllowed, NotFound, ValidationFailed


@dataclass(frozen=True, slots=True)
class _Stored:
    """What the replay store keeps for a command key: its fingerprint and its first result."""

    fingerprint: str
    result: SavePushSubscriptionResult | RemovePushSubscriptionResult


AUDIT_ACTION: Final = "U"
SAVE_USE_CASE: Final = "SavePushSubscription"
REMOVE_USE_CASE: Final = "RemovePushSubscription"
MAX_WORDING_VERSION_LENGTH: Final = 32


@dataclass(frozen=True, slots=True)
class SavePushSubscriptionCommand:
    idempotency_key: str
    actor: Actor
    device_id: str
    subscription: dict[str, Any]
    wording_version: str


@dataclass(frozen=True, slots=True)
class SavePushSubscriptionResult:
    device_id: str
    consent_at: datetime


@dataclass(frozen=True, slots=True)
class RemovePushSubscriptionCommand:
    idempotency_key: str
    actor: Actor
    device_id: str


@dataclass(frozen=True, slots=True)
class RemovePushSubscriptionResult:
    device_id: str


def _practitioner(actor: Actor) -> str:
    if actor.practitioner_id is None:
        raise NotAllowed("a push subscription belongs to a practitioner")
    return actor.practitioner_id


def _tenant_scope(scope: ScopeId | None) -> ScopeId:
    if scope is None or scope.kind is not ScopeKind.TENANT:
        raise TenantNotBound
    return scope


def _check_device(device_id: str) -> None:
    if not isinstance(device_id, str) or not device_id or len(device_id) > 64:
        raise ValidationFailed("device_id", "is required and must be at most 64 characters")


def _check_wording(version: str) -> None:
    if not isinstance(version, str) or not version.strip():
        raise ValidationFailed("wording_version", "is required")
    if len(version) > MAX_WORDING_VERSION_LENGTH:
        raise ValidationFailed("wording_version", "is too long")


def _save_fingerprint(command: SavePushSubscriptionCommand, practitioner: str) -> str:
    """What the command says. The subscription text is part of it, so a replay with a different
    endpoint is a different command; the fingerprint is never stored or logged on its own."""
    subscription = json.dumps(command.subscription, sort_keys=True, default=str)
    return repr(("save", practitioner, command.device_id, subscription, command.wording_version))


class SavePushSubscription:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        clock: Clock,
        ids: IdGenerator,
        idempotency: IdempotencyStore,
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._ids = ids
        self._idempotency = idempotency

    async def execute(self, command: SavePushSubscriptionCommand) -> SavePushSubscriptionResult:
        practitioner = _practitioner(command.actor)
        _check_device(command.device_id)
        _check_wording(command.wording_version)
        fingerprint = _save_fingerprint(command, practitioner)
        now = self._clock.now()
        key = _command_key("save", current_scope(), command.idempotency_key)
        early = await self._idempotency.get(key)
        if early is not None:
            return _replay(early, fingerprint, SavePushSubscriptionResult)

        async with self._uow_factory() as uow:
            _tenant_scope(uow.unit_scope)
            stored = await uow.idempotency.get(key)
            if stored is not None:
                return _replay(stored, fingerprint, SavePushSubscriptionResult)
            await uow.push_subscriptions.save(
                PushSubscription(
                    device_id=command.device_id,
                    practitioner_id=practitioner,
                    subscription=command.subscription,
                    saved_at=now,
                )
            )
            await uow.notification_consents.record(
                practitioner, command.device_id, command.wording_version, now
            )
            await uow.audit.append(
                AuditEntry(
                    action=AUDIT_ACTION,
                    use_case=SAVE_USE_CASE,
                    actor=command.actor,
                    entity_ids=(command.device_id,),
                    snapshot={"wording_version": command.wording_version},
                    at=now,
                )
            )
            result = SavePushSubscriptionResult(device_id=command.device_id, consent_at=now)
            await uow.idempotency.put(key, _Stored(fingerprint, result))
            await uow.commit()
        return result


class RemovePushSubscription:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        clock: Clock,
        ids: IdGenerator,
        idempotency: IdempotencyStore,
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._ids = ids
        self._idempotency = idempotency

    async def execute(self, command: RemovePushSubscriptionCommand) -> RemovePushSubscriptionResult:
        practitioner = _practitioner(command.actor)
        _check_device(command.device_id)
        fingerprint = repr(("remove", practitioner, command.device_id))
        now = self._clock.now()
        key = _command_key("remove", current_scope(), command.idempotency_key)
        early = await self._idempotency.get(key)
        if early is not None:
            return _replay(early, fingerprint, RemovePushSubscriptionResult)

        async with self._uow_factory() as uow:
            _tenant_scope(uow.unit_scope)
            stored = await uow.idempotency.get(key)
            if stored is not None:
                return _replay(stored, fingerprint, RemovePushSubscriptionResult)
            owned = await uow.push_subscriptions.for_practitioner(practitioner)
            if not any(sub.device_id == command.device_id for sub in owned):
                raise NotFound("no push subscription for this device")
            await uow.push_subscriptions.delete(command.device_id)
            await uow.notification_consents.withdraw(practitioner, command.device_id, now)
            await uow.audit.append(
                AuditEntry(
                    action=AUDIT_ACTION,
                    use_case=REMOVE_USE_CASE,
                    actor=command.actor,
                    entity_ids=(command.device_id,),
                    snapshot=None,
                    at=now,
                )
            )
            result = RemovePushSubscriptionResult(device_id=command.device_id)
            await uow.idempotency.put(key, _Stored(fingerprint, result))
            await uow.commit()
        return result


def _command_key(kind: str, scope: ScopeId, key: str) -> str:
    """The replay key. It carries the tenant (lesson L160): one key, two tenants, two commands."""
    return f"push-{kind}:{scope}:{key}"


def _replay[T](stored: object, fingerprint: str, result_type: type[T]) -> T:
    """The first result of this key, when the command is the same one (DEC-104). A different
    command under the same key is a Conflict."""
    if (
        not isinstance(stored, _Stored)
        or stored.fingerprint != fingerprint
        or not isinstance(stored.result, result_type)
    ):
        raise Conflict("this command key was used for a different command")
    return stored.result
