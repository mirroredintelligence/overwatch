"""Which board a wall screen shows: the setting, its change and what a screen reads of it (TEN-067,
DEC-132 item 5).

A wall screen is paired to one tenant and shows that tenant's board, or the board of a network its
tenant is an active member of. The setting is on the screen's own record, in the tenant's scope
(`Device.board_scope`, `Device.network_id`, `Device.scope_version`). It is not in the screen's
token: an administrator can change it without pairing again, and a stolen token cannot widen what
its screen sees. Every read of a network board by a wall asks the record, never the caller
(`NetworkAccess.require_wall`).

- `ListScreens`: the tenant's wall screens with what each shows, and the networks an administrator
  may choose (the active memberships of the tenant: a page never offers a network the server did
  not).
- `SetScreenBoardScope`: change one screen's setting, with the version the administrator read
  (`If-Match`). `network` needs an active membership of an active network; any cause of refusal is
  the one NotFound, so a network id and who belongs to it cannot be discovered. A change is audited
  in the tenant's chain (the screen, the board and the network id: nothing about a person beyond the
  administrator's role). Setting what is already set changes nothing and writes nothing.
- `ReadWallScope`: what a screen reads of its own setting: the board it should show now, and a
  `fallback` flag when it is set to a network it can no longer read, so it shows the tenant board
  with a banner instead of a blank (design: `NetworkWallFallback`).

Roles. The shift lead and the tenant administrator may list and set: the lead already pairs screens
(R15), and the board a screen shows is what the lead may read anyway. No other role may.
"""

from dataclasses import dataclass, replace
from typing import Final

from diucs.application.actor import Actor, tenant_scope_of_unit
from diucs.application.network_access import NetworkAccess
from diucs.application.ports.outbound.audit import AuditEntry
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.domain.codes import Role
from diucs.domain.errors import Conflict, DomainError, NotAllowed, NotFound, ValidationFailed
from diucs.domain.model.device import BoardScope, Device, DeviceStatus
from diucs.domain.model.network import check_network_id

USE_CASE: Final = "SetScreenBoardScope"
ACTION_SET: Final = "wall-screen-board-set"
ADMIN_ROLES: Final[frozenset[Role]] = frozenset({Role.LEAD, Role.TENANT_ADMIN})
ADMIN_ONLY: Final = "only a shift lead or a tenant administrator may change a screen"
NO_SCREEN: Final = "the screen was not found"
FALLBACK_REASON: Final = "network-unavailable"
"""The fixed reason a screen is told it shows its own board: the network it is set to is not open to
it (its tenant left, or the network is not active). The word names no network."""


class ScreenSettingChanged(DomainError):
    """The setting changed since the version the caller read (the route answers 412)."""

    def __init__(self) -> None:
        super().__init__("the screen's board setting has changed")


@dataclass(frozen=True, slots=True)
class NetworkOption:
    """A network an administrator may choose: the registry's name of an active membership."""

    id: str
    name: str


@dataclass(frozen=True, slots=True)
class ScreenSetting:
    """One screen as an administrator sees it. `network_name` is None when the screen shows its own
    board, or when the network it is set to is not open to the tenant now (`network_available`)."""

    id: str
    name: str
    location: str | None
    status: DeviceStatus
    board_scope: BoardScope
    network_id: str | None
    network_name: str | None
    network_available: bool
    scope_version: int


@dataclass(frozen=True, slots=True)
class ScreenList:
    screens: tuple[ScreenSetting, ...]
    networks: tuple[NetworkOption, ...]


@dataclass(frozen=True, slots=True)
class SetBoardScopeCommand:
    actor: Actor
    device_id: str
    board_scope: BoardScope
    network_id: str | None
    expected_version: int
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class WallScope:
    """What a screen reads of its own setting. `network_name` is set only when the screen shows a
    network now. `fallback` is True when it is set to a network it can no longer read and so shows
    its tenant's board: the page says so."""

    shows: BoardScope
    network_name: str | None
    fallback: bool
    scope_version: int


def _check_admin(actor: Actor) -> None:
    if actor.role not in ADMIN_ROLES:
        raise NotAllowed(ADMIN_ONLY)


class UowScreens:
    """The screens of the bound tenant through a unit of work: the reader `NetworkAccess` uses for a
    wall. A read, without the screen's lock."""

    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def screen(self, device_id: str) -> Device | None:
        async with self._uow_factory() as uow:
            return await uow.devices.peek(device_id)


class ListScreens:
    def __init__(self, uow_factory: UnitOfWorkFactory, access: NetworkAccess) -> None:
        self._uow_factory = uow_factory
        self._access = access

    async def execute(self, actor: Actor) -> ScreenList:
        _check_admin(actor)
        contexts = await self._access.networks_of_tenant(actor.tenant_id)
        names = {context.network.id: context.network.name for context in contexts}
        async with self._uow_factory() as uow:
            devices = await uow.devices.list_screens()
        screens = tuple(
            ScreenSetting(
                id=device.id,
                name=device.name,
                location=device.location,
                status=device.status,
                board_scope=device.board_scope,
                network_id=device.network_id,
                network_name=None if device.network_id is None else names.get(device.network_id),
                network_available=device.network_id is None or device.network_id in names,
                scope_version=device.scope_version,
            )
            for device in devices
        )
        options = tuple(NetworkOption(network_id, name) for network_id, name in names.items())
        return ScreenList(screens, options)


class SetScreenBoardScope:
    def __init__(self, uow_factory: UnitOfWorkFactory, access: NetworkAccess, clock: Clock) -> None:
        self._uow_factory = uow_factory
        self._access = access
        self._clock = clock

    async def execute(self, command: SetBoardScopeCommand) -> ScreenSetting:
        actor = command.actor
        _check_admin(actor)
        network_id = _checked_target(command)
        network_name: str | None = None
        if network_id is not None:
            # The registry is read before the unit opens: a unit holds one scope (DEC-130 item 7).
            member = await self._access.require_tenant_member(actor.tenant_id, network_id)
            network_name = member.network.name
        async with self._uow_factory() as uow:
            scope = tenant_scope_of_unit(uow.unit_scope, actor)
            key = f"screen-board:{scope}:{command.idempotency_key}"
            stored = await uow.idempotency.get(key)
            if stored is not None:
                return _replayed(stored, command)
            device = await uow.devices.get(command.device_id)
            if device is None or device.status is DeviceStatus.REVOKED:
                raise NotFound(NO_SCREEN)
            if command.expected_version != device.scope_version:
                raise ScreenSettingChanged
            if device.board_scope is command.board_scope and device.network_id == network_id:
                changed = device
            else:
                changed = replace(
                    device,
                    board_scope=command.board_scope,
                    network_id=network_id,
                    scope_version=device.scope_version + 1,
                )
                await uow.devices.save(changed)
                await uow.audit.append(
                    AuditEntry(
                        action=ACTION_SET,
                        use_case=USE_CASE,
                        actor=actor,
                        entity_ids=(changed.id,),
                        snapshot={
                            "board_scope": changed.board_scope.value,
                            "network_id": changed.network_id,
                            "scope_version": changed.scope_version,
                        },
                        at=self._clock.now(),
                    )
                )
            setting = _setting(changed, network_name)
            await uow.idempotency.put(key, _Stored(_fingerprint(command), setting))
            await uow.commit()
        return setting


@dataclass(frozen=True, slots=True)
class _Stored:
    fingerprint: str
    setting: ScreenSetting


def _fingerprint(command: SetBoardScopeCommand) -> str:
    return repr(
        (
            USE_CASE,
            command.actor.role.value,
            command.device_id,
            command.board_scope.value,
            command.network_id,
            command.expected_version,
        )
    )


def _replayed(stored: object, command: SetBoardScopeCommand) -> ScreenSetting:
    if not isinstance(stored, _Stored) or stored.fingerprint != _fingerprint(command):
        raise Conflict("this command key was used for a different command")
    return stored.setting


def _checked_target(command: SetBoardScopeCommand) -> str | None:
    """The network id the command asks for: required for `network`, absent for `tenant`."""
    if type(command.board_scope) is not BoardScope:
        raise ValidationFailed("board_scope", "must be tenant or network")
    if command.board_scope is BoardScope.NETWORK:
        if command.network_id is None:
            raise ValidationFailed("network_id", "a network board needs a network")
        return check_network_id(command.network_id)
    if command.network_id is not None:
        raise ValidationFailed("network_id", "the tenant board has no network")
    return None


def _setting(device: Device, network_name: str | None) -> ScreenSetting:
    return ScreenSetting(
        id=device.id,
        name=device.name,
        location=device.location,
        status=device.status,
        board_scope=device.board_scope,
        network_id=device.network_id,
        network_name=network_name,
        network_available=device.network_id is None or network_name is not None,
        scope_version=device.scope_version,
    )


class ReadWallScope:
    def __init__(self, access: NetworkAccess) -> None:
        self._access = access

    async def execute(self, actor: Actor) -> WallScope:
        """The setting of the screen the token names. Another role is NotAllowed and a screen that
        is not found or not active is NotFound, with the same answers as every wall read."""
        device, member = await self._access.screen_network(actor)
        if device.board_scope is not BoardScope.NETWORK:
            return WallScope(BoardScope.TENANT, None, False, device.scope_version)
        if member is None:
            return WallScope(BoardScope.TENANT, None, True, device.scope_version)
        return WallScope(BoardScope.NETWORK, member.network.name, False, device.scope_version)
