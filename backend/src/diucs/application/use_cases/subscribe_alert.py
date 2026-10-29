"""SaveAlertPreferences and GetAlertPreferences (U33): what an exec or shift lead is alerted about.

A COO, ICB lead or shift lead chooses the alert kinds they get, the not-updated threshold (2 or 4
hours), quiet hours (none, or 22:00 to 06:00), what they get during quiet hours, how fast they must
acknowledge (10, 15 or 30 minutes), their deputy, and the daily and weekly summaries. The rules are
the D24 rules (diucs.domain.rules.alerts); the record is P17's AlertSubscription, one per
practitioner, stored by the alert subscription repository.

A user changes only their own preferences: the command names no target, so the subscription saved
is the actor's (structural, not a check). The deputy is another active practitioner who holds a
leadership role (shift lead or clinical lead, the codes the graph has; an exec role is not held in
the graph, see the fragment). Replays use the tenant-scoped command key (lesson L160).

The audit entry records the kinds chosen and nothing else.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, time
from typing import Final

from diucs.application.actor import Actor
from diucs.application.idempotency import IdempotencyStore
from diucs.application.ports.outbound.audit import AuditEntry
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.unit_of_work import UnitOfWork, UnitOfWorkFactory
from diucs.application.tenancy import ScopeId, ScopeKind, TenantNotBound, current_scope
from diucs.domain.codes import AlertKind, PractitionerRoleCode, Role
from diucs.domain.errors import Conflict, NotAllowed, NotFound, ValidationFailed
from diucs.domain.model.alerts import AlertSubscription
from diucs.domain.rules.alerts import AlertPreferences, default_preferences

AUDIT_ACTION: Final = "U"
USE_CASE: Final = "SaveAlertPreferences"
NEVER_SAVED: Final = datetime(1970, 1, 1, tzinfo=UTC)
"""The updated_at of the defaults a user gets before any save: the epoch means never saved."""
DEFAULT_DAILY_SUMMARY: Final = True
DEFAULT_WEEKLY_SUMMARY: Final = False
ALLOWED_ROLES: Final = frozenset({Role.EXEC, Role.LEAD})
DEPUTY_CODES: Final = frozenset(
    {PractitionerRoleCode.SHIFT_LEAD, PractitionerRoleCode.CLINICAL_LEAD}
)


@dataclass(frozen=True, slots=True)
class SaveAlertPreferencesCommand:
    idempotency_key: str
    actor: Actor
    kinds: frozenset[AlertKind]
    not_updated_hours: int
    quiet_hours: tuple[time, time] | None
    quiet_critical_only: bool
    ack_minutes: int
    deputy_id: str | None
    daily_summary: bool
    weekly_summary: bool


@dataclass(frozen=True, slots=True)
class SavedAlertPreferences:
    """What the replay store keeps: the practitioner and the save instant (plain types only, since
    the store cannot hold a time of day)."""

    practitioner_id: str
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class _Stored:
    fingerprint: str
    result: SavedAlertPreferences


def _practitioner(actor: Actor) -> str:
    if actor.role not in ALLOWED_ROLES:
        raise NotAllowed("only an exec or a shift lead may set alert preferences")
    if actor.practitioner_id is None:
        raise NotAllowed("alert preferences belong to a practitioner")
    return actor.practitioner_id


def _tenant_scope(scope: ScopeId | None) -> ScopeId:
    if scope is None or scope.kind is not ScopeKind.TENANT:
        raise TenantNotBound
    return scope


def _preferences(command: SaveAlertPreferencesCommand) -> AlertPreferences:
    """The D24 rules, which refuse a threshold, a window or a kind that is not allowed."""
    if any(type(kind) is not AlertKind for kind in command.kinds):
        raise ValidationFailed("kinds", "must be alert kinds")
    return AlertPreferences(
        kinds=command.kinds,
        not_updated_hours=command.not_updated_hours,
        quiet_hours=command.quiet_hours,
        quiet_critical_only=command.quiet_critical_only,
        ack_minutes=command.ack_minutes,
    )


def _command_key(scope: ScopeId, key: str) -> str:
    return f"alerts-save:{scope}:{key}"


def _fingerprint(
    practitioner: str, prefs: AlertPreferences, command: SaveAlertPreferencesCommand
) -> str:
    kinds = sorted(kind.value for kind in prefs.kinds)
    quiet = None if prefs.quiet_hours is None else tuple(t.isoformat() for t in prefs.quiet_hours)
    return repr(
        (
            practitioner,
            kinds,
            prefs.not_updated_hours,
            quiet,
            prefs.quiet_critical_only,
            prefs.ack_minutes,
            command.deputy_id,
            command.daily_summary,
            command.weekly_summary,
        )
    )


class SaveAlertPreferences:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        idempotency: IdempotencyStore,
        clock: Clock,
    ) -> None:
        self._uow_factory = uow_factory
        self._idempotency = idempotency
        self._clock = clock

    async def execute(self, command: SaveAlertPreferencesCommand) -> AlertSubscription:
        who = _practitioner(command.actor)
        prefs = _preferences(command)
        if command.kinds and command.deputy_id is None:
            raise ValidationFailed("deputy_id", "is required when an alert kind is on")
        if command.deputy_id == who:
            raise ValidationFailed("deputy_id", "must be another person")
        fingerprint = _fingerprint(who, prefs, command)
        key = _command_key(current_scope(), command.idempotency_key)
        early = await self._idempotency.get(key)
        if isinstance(early, _Stored):
            return await self._replay(early, fingerprint, who)

        now = self._clock.now()
        async with self._uow_factory() as uow:
            _tenant_scope(uow.unit_scope)
            stored = await uow.idempotency.get(key)
            if isinstance(stored, _Stored):
                return await self._replay(stored, fingerprint, who)
            if command.deputy_id is not None:
                await _check_deputy(uow, command.deputy_id)
            subscription = AlertSubscription(
                practitioner_id=who,
                preferences=prefs,
                deputy_id=command.deputy_id,
                daily_summary=command.daily_summary,
                weekly_summary=command.weekly_summary,
                updated_at=now,
            )
            await uow.alert_subscriptions.save(subscription)
            await uow.audit.append(
                AuditEntry(
                    action=AUDIT_ACTION,
                    use_case=USE_CASE,
                    actor=command.actor,
                    entity_ids=(who,),
                    snapshot={"kinds": sorted(kind.value for kind in prefs.kinds)},
                    at=now,
                )
            )
            await uow.idempotency.put(key, _Stored(fingerprint, SavedAlertPreferences(who, now)))
            await uow.commit()
        return subscription

    async def _replay(self, stored: _Stored, fingerprint: str, who: str) -> AlertSubscription:
        """The result of the first command under this key, when the command is the same one
        (DEC-104). The subscription is read back as stored now."""
        if stored.fingerprint != fingerprint:
            raise Conflict("this command key was used for different alert preferences")
        async with self._uow_factory() as uow:
            current = await uow.alert_subscriptions.get_for_practitioner(who)
        if current is None:
            raise NotFound("alert preferences")
        return current


async def _check_deputy(uow: UnitOfWork, deputy_id: str) -> None:
    """The deputy must be an active practitioner who holds a leadership role. Reads are within
    the bound tenant (the repositories are scoped)."""
    people = uow.people
    deputy = await people.get_practitioner(deputy_id)
    if deputy is None or not deputy.active:
        raise ValidationFailed("deputy_id", "is not an active practitioner")
    roles = await people.roles_for_practitioner(deputy_id)
    if not any(role.code in DEPUTY_CODES for role in roles):
        raise ValidationFailed("deputy_id", "must hold a shift lead or clinical lead role")


class GetAlertPreferences:
    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def execute(self, actor: Actor) -> AlertSubscription:
        who = _practitioner(actor)
        async with self._uow_factory() as uow:
            stored = await uow.alert_subscriptions.get_for_practitioner(who)
        if stored is not None:
            return stored
        return AlertSubscription(
            practitioner_id=who,
            preferences=default_preferences(),
            deputy_id=None,
            daily_summary=DEFAULT_DAILY_SUMMARY,
            weekly_summary=DEFAULT_WEEKLY_SUMMARY,
            updated_at=NEVER_SAVED,
        )
