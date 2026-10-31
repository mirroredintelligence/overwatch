"""ConfirmCapacity: a Y that says the figure on record is still right (U02).

A confirmation is a new CapacityReport of type confirmed, with the value of the latest report and
derived_from set to that report. At most MAX_CONSECUTIVE_CONFIRMS may follow one number report; a
further one is refused and nothing is written.

Tenancy (TEN-027, DEC-500): the actor's tenant must be the tenant the unit is bound to, checked
before anything is read; a service of another tenant reads as an id nobody has (the store is
tenant-scoped); the performer role is validated as ReportCapacity's is (it becomes the echo
recipient); the limit of consecutive confirmations and the policy that judges the status are the
tenant's own, and the audit entry names the configuration version they came from.

The unit of work takes the service's write lock first, then reads the latest report and the count,
then takes the effective time and writes (DEC-112 items 8 and 10, DEC-139; lessons L73, L99). Two
confirmations for one service therefore run one after the other. A caller that judged a report
passes its id as `expected_latest_id`; the latest read under the lock must be that report, or
nothing is written (DEC-148 item 18). The write itself goes through
record_report (U01), which also writes the echo, status events, audit entry and idempotency record
in the same unit of work.
"""

import hashlib
from dataclasses import dataclass, replace
from datetime import datetime

from diucs.application.actor import Actor, require_actor_in_bound_tenant, tenant_scope_of_unit
from diucs.application.idempotency import IdempotencyStore
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.ids import IdGenerator
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.tenant_settings import TenantZones, as_zones, read_settings
from diucs.application.use_cases.report_capacity import (
    check_may_report,
    check_performer,
    record_report,
)
from diucs.domain.codes import ReportSource, ReportType, Status
from diucs.domain.errors import (
    ConfirmLimitReached,
    Conflict,
    LatestReportChanged,
    NotFound,
    NothingToConfirm,
)
from diucs.domain.model.capacity import CapacityReport
from diucs.domain.model.tenant_policy import TenantPolicy
from diucs.domain.rules.effective_time import default_effective_at

USE_CASE = "ConfirmCapacity"


@dataclass(frozen=True, slots=True)
class ConfirmCapacityCommand:
    idempotency_key: str
    actor: Actor
    service_id: str
    source: ReportSource
    performer_role_id: str | None = None
    send_echo: bool = True
    """False when the caller sends its own reply: U05 answers a grouped text with one C10 (DEC-148).
    The performer is recorded either way."""
    expected_latest_id: str | None = None
    """The report the caller judged, or None for a caller that did not judge one. When set, the
    confirmation is refused, and nothing is written, unless the latest report of the service, read
    under the service lock, is this one (DEC-148 item 18)."""


@dataclass(frozen=True, slots=True)
class ConfirmCapacityResult:
    report_id: str
    status: Status
    status_changed: bool
    next_due: datetime | None
    confirmed_value: int
    replayed: bool = False


@dataclass(frozen=True, slots=True)
class _StoredConfirm:
    """The result kept for a command key, with the fingerprint of the command that made it."""

    fingerprint: str
    result: ConfirmCapacityResult


def _fingerprint(command: ConfirmCapacityCommand) -> str:
    body = repr(
        (
            USE_CASE,
            command.actor.tenant_id,
            command.service_id,
            command.source.value,
            command.performer_role_id,
            command.actor.role.value,
            command.actor.practitioner_id,
            command.send_echo,
        )
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def check_confirm_limit(trailing: int, policy: TenantPolicy) -> None:
    """Refuse a confirmation when `trailing` confirmations already follow the last number report
    and the tenant's limit has been reached (the default is two, domain-rules 1.2)."""
    if trailing >= policy.max_consecutive_confirms:
        raise ConfirmLimitReached("confirmed twice in a row: give the figure again")


def _replay(stored: object, fingerprint: str) -> ConfirmCapacityResult:
    """A stored result for this key replays only for the same command by the same actor. Any other
    stored value, including a key that ReportCapacity stored, is a Conflict (DEC-112 item 6)."""
    if not isinstance(stored, _StoredConfirm) or stored.fingerprint != fingerprint:
        raise Conflict("this command key was used for a different command")
    return replace(stored.result, replayed=True)


class ConfirmCapacity:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        clock: Clock,
        ids: IdGenerator,
        idempotency: IdempotencyStore,
        zones: TenantZones | None = None,
    ) -> None:
        """`zones` is the tenant's time zone source; None is London, the one zone on the allow-list
        (KI-415). The serving process passes `DirectoryZones`."""
        self._uow_factory = uow_factory
        self._clock = clock
        self._ids = ids
        self._idempotency = idempotency
        self._zones = as_zones(zones)

    async def execute(self, command: ConfirmCapacityCommand) -> ConfirmCapacityResult:
        # Before anything is read, the early replay included: the actor's tenant is the bound one
        # (a wiring fault otherwise, never an access decision) and a tenant is bound at all.
        require_actor_in_bound_tenant(command.actor)
        fingerprint = _fingerprint(command)
        # An early read outside the unit of work. The authoritative check is inside it.
        early = await self._idempotency.get(command.idempotency_key)
        if early is not None:
            return _replay(early, fingerprint)

        async with self._uow_factory() as uow:
            # The unit opened under the actor's tenant, and under a tenant at all. Checked before
            # the lock, so a unit of another scope takes none.
            tenant_scope_of_unit(uow.unit_scope, command.actor)
            # The service lock comes before every read that decides the count, and before the
            # effective time is taken (DEC-139): a confirmation that waits behind a report is timed
            # after it.
            await uow.capacity.lock_service(command.service_id)
            now = self._clock.now()
            stored = await uow.idempotency.get(command.idempotency_key)
            if stored is not None:
                return _replay(stored, fingerprint)

            profile = await uow.services.get(command.service_id)
            if profile is None or not profile.active:
                raise NotFound("no active service with this id")
            check_may_report(command.actor, command.source, profile.id)
            if command.performer_role_id is not None:
                # After the permission check, so a caller who may not confirm learns nothing about
                # which roles exist; the store answers None for another tenant's role (TEN-024).
                check_performer(
                    await uow.people.get_role(command.performer_role_id),
                    service_id=profile.id,
                    actor=command.actor,
                    now=now,
                )

            latest = await uow.capacity.latest(profile.id)
            if latest is None:
                raise NothingToConfirm("this service has no report to confirm")
            if command.expected_latest_id is not None and latest.id != command.expected_latest_id:
                # The caller judged another report. A report landed since, so what would be
                # confirmed is a figure nobody judged: write nothing (DEC-148 item 18).
                raise LatestReportChanged(
                    "the latest report is not the one that was judged",
                    latest.value,
                    latest.effective_at,
                )
            settings = await read_settings(uow, self._zones)
            policy = settings.policy
            trailing = await uow.capacity.trailing_confirmations(profile.id)
            check_confirm_limit(trailing, policy)

            report = CapacityReport(
                id=self._ids.new_id(),
                service_id=profile.id,
                value=latest.value,
                measure=profile.measure,
                # Never at or before the figure it confirms: a host whose clock is behind the one
                # that wrote it would otherwise time the confirmation before the figure (KI-8).
                effective_at=default_effective_at(now, latest.effective_at),
                source=command.source,
                report_type=ReportType.CONFIRMED,
                performer_role_id=command.performer_role_id,
                derived_from=latest.id,
            )
            send_echo = (
                command.performer_role_id
                if command.source is ReportSource.TEXT and command.send_echo
                else None
            )
            recorded = await record_report(
                uow,
                profile=profile,
                report=report,
                actor=command.actor,
                now=now,
                ids=self._ids,
                send_echo=send_echo,
                replaced_value=None,
                use_case=USE_CASE,
                audit_snapshot={
                    "value": report.value,
                    "derived_from": latest.id,
                    "consecutive": trailing + 1,
                    **(
                        {}
                        if settings.config_version is None
                        else {"config_version": settings.config_version}
                    ),
                },
                policy=policy,
                config_version=settings.config_version,
                zone=settings.zone,
            )
            result = ConfirmCapacityResult(
                report_id=recorded.report_id,
                status=recorded.status,
                status_changed=recorded.status_changed,
                next_due=recorded.next_due,
                confirmed_value=report.value,
            )
            await uow.idempotency.put(command.idempotency_key, _StoredConfirm(fingerprint, result))
            await uow.commit()
        return result
