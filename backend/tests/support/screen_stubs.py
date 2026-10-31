"""A stand-in wall screen registry for the unit tests of the screen administration (W9I).

It holds the wall screens of one tenant by id and records what was written, like the other
recording stand-ins. It keeps no record the product reads (DEC-004): the flow against the graph is
the integration tests'. Values are synthetic.
"""

from dataclasses import replace
from datetime import datetime, timedelta

from diucs.domain.model.device import Device, DeviceStatus
from tests.support.w7b_rig import W7BDevices


class ScreenDevices(W7BDevices):
    """The device stub of the W7B rig with the wall screens of the tenant."""

    def __init__(self, writes, calls) -> None:  # type: ignore[no-untyped-def]
        super().__init__(writes, calls)
        self.screens: dict[str, Device] = {}

    async def get(self, device_id: str) -> Device | None:
        self._calls.append("devices.get")
        return self.screens.get(device_id)

    async def save(self, device: Device) -> None:
        self.wrote("save")
        self.screens[device.id] = device

    async def list_screens(self) -> list[Device]:
        self._calls.append("devices.list_screens")
        return list(self.screens.values())

    async def confirm_active(
        self, device_id: str, seen_at: datetime, refresh_after: timedelta
    ) -> bool:
        self._calls.append("devices.confirm_active")
        screen = self.screens.get(device_id)
        if screen is None or screen.status is not DeviceStatus.ACTIVE:
            return False
        if screen.last_seen_at is None or screen.last_seen_at < seen_at - refresh_after:
            self.wrote("seen")
            self.screens[device_id] = replace(screen, last_seen_at=seen_at)
        return True
