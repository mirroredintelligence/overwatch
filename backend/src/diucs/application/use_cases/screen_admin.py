"""The lead's wall screen administration: the list and the revoke (W9I, TEN-072, TEN-043).

- `ListWallScreens`: the screens of the lead's tenant, each with its name, place, state (online,
  offline, waiting, never connected, revoked), the board it shows, when it was paired, when it was
  last seen and when it was revoked. A token, a token hash or a pairing secret is not in a view: the
  view has no field for one. Live screens come first by name; a revoked one comes last, and stays
  listed for `REVOKED_LISTED_FOR` so the lead can see that it ended.
- `RevokeWallScreen`: ends a screen. Its record becomes `revoked` and loses its token hash, so the
  device token finds nothing and the exchange gives no new wall token (`find_by_token_hash` returns
  active screens only), and the edge refuses the wall token the screen already holds on its next
  request (`auth.ensure_screen_live`, which asks the registry whether the screen is still active).
  The lead is audited once. A screen that is revoked already is answered as it is and audited no
  second time; a screen the tenant does not hold (another tenant's included) is NotFound.

Both are for the shift lead alone, checked before anything is read. The tenant is the unit's (bound
at the edge); nothing here takes one. The network scope (TEN-072's other half) lists screens of
member tenants by another use case over the same view: a new use case, not a parameter of these.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Final

from diucs.application.actor import Actor
from diucs.application.ports.outbound.audit import AuditEntry
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.tenancy import ScopeKind, TenantNotBound
from diucs.application.use_cases.lead_views import check_lead
from diucs.domain.errors import NotAllowed, NotFound
from diucs.domain.model.device import (
    REVOKED_LISTED_FOR,
    BoardScope,
    Device,
    DeviceStatus,
    ScreenState,
    screen_state,
)

USE_CASE_REVOKE: Final = "RevokeWallScreen"
ACTION_REVOKED: Final = "wall-screen-revoked"
NO_SCREEN: Final = "no screen with this id"


@dataclass(frozen=True, slots=True)
class ScreenSummary:
    device_id: str
    name: str
    location: str | None
    state: ScreenState
    board_scope: BoardScope
    paired_at: datetime | None
    last_seen_at: datetime | None
    revoked_at: datetime | None


@dataclass(frozen=True, slots=True)
class RevokeWallScreenCommand:
    actor: Actor
    device_id: str


@dataclass(frozen=True, slots=True)
class RevokeResult:
    device_id: str
    revoked_at: datetime | None
    already_revoked: bool


def _summary(device: Device, now: datetime) -> ScreenSummary:
    return ScreenSummary(
        device_id=device.id,
        name=device.name,
        location=device.location,
        state=screen_state(device, now),
        board_scope=device.board_scope,
        paired_at=device.paired_at,
        last_seen_at=device.last_seen_at,
        revoked_at=device.revoked_at,
    )


def _listed(device: Device, now: datetime) -> bool:
    if device.status is not DeviceStatus.REVOKED or device.revoked_at is None:
        return True
    return now - device.revoked_at < REVOKED_LISTED_FOR


class ListWallScreens:
    def __init__(self, uow_factory: UnitOfWorkFactory, clock: Clock) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    async def execute(self, actor: Actor) -> list[ScreenSummary]:
        check_lead(actor)
        now = self._clock.now()
        async with self._uow_factory() as uow:
            found = await uow.devices.list_screens()
        shown = [_summary(device, now) for device in found if _listed(device, now)]
        return sorted(
            shown,
            key=lambda view: (
                view.state is ScreenState.REVOKED,
                view.name.casefold(),
                view.device_id,
            ),
        )


class RevokeWallScreen:
    def __init__(self, uow_factory: UnitOfWorkFactory, clock: Clock) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    async def execute(self, command: RevokeWallScreenCommand) -> RevokeResult:
        actor = command.actor
        check_lead(actor)
        if actor.practitioner_id is None:
            raise NotAllowed("the lead must act as a named practitioner")
        now = self._clock.now()
        async with self._uow_factory() as uow:
            scope = uow.unit_scope
            if scope is None or scope.kind is not ScopeKind.TENANT:
                raise TenantNotBound
            # `get` takes the screen's write lock, so a claim that is running for it finishes first
            # and the revoke is the last word on the record (L85).
            device = await uow.devices.get(command.device_id)
            if device is None:
                raise NotFound(NO_SCREEN)
            if device.status is DeviceStatus.REVOKED:
                return RevokeResult(device.id, device.revoked_at, already_revoked=True)
            ended = device.revoke(now)
            await uow.devices.save(ended)
            await uow.audit.append(
                AuditEntry(
                    action=ACTION_REVOKED,
                    use_case=USE_CASE_REVOKE,
                    actor=actor,
                    entity_ids=(device.id,),
                    snapshot={"screen_name": device.name, "was": device.status.value},
                    at=now,
                )
            )
            await uow.commit()
        return RevokeResult(device.id, ended.revoked_at, already_revoked=False)
