"""Service Bus helpers for the emulator suites (I02). Nothing here reaches a cloud namespace.

The emulator is one process for the whole machine, and the suites share its queues
(`scheduled.work`, `inbound.receipts`). A contract test drains a queue before it starts and then
waits for its own due message, so a second run receiving from the same queue can take that message
and the test sees None. `take_emulator_lock` lets one run at a time hold the emulator.
"""

import asyncio
import fcntl
import os
import time
from collections.abc import Callable

from azure.servicebus.aio import ServiceBusClient

from diucs.bootstrap.settings import Settings

# The emulator's documented local development connection string (infra/README.md). It is a
# public key for the local emulator only; a real namespace uses DIUCS_SERVICEBUS_CONNECTION.
EMULATOR_CONNECTION = (
    "Endpoint=sb://localhost;SharedAccessKeyName=RootManageSharedAccessKey;"
    "SharedAccessKey=SAS_KEY_VALUE;UseDevelopmentEmulator=true"
)
EMULATOR_LOCK_PATH = "/tmp/diucs-servicebus-emulator.lock"
# A contract run takes about six minutes; several queued runs are well inside this.
EMULATOR_LOCK_TIMEOUT_S = 3600.0
_POLL_INTERVAL_S = 0.25


class EmulatorBusy(TimeoutError):
    """The emulator lock stayed taken for the whole timeout."""


async def take_emulator_lock(
    path: str = EMULATOR_LOCK_PATH, timeout_s: float = EMULATOR_LOCK_TIMEOUT_S
) -> Callable[[], None]:
    """Hold an exclusive flock on `path` until the returned function is called. Waits up to
    timeout_s, polling so the event loop keeps running. The OS drops the flock if the process dies,
    so a killed run never blocks the next one."""
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        deadline = time.monotonic() + timeout_s
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise EmulatorBusy(f"{path} was still held after {timeout_s} s") from None
                await asyncio.sleep(_POLL_INTERVAL_S)
    except BaseException:
        os.close(fd)
        raise

    def release() -> None:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)

    return release


def connection_string() -> str:
    secret = Settings().servicebus_connection
    return secret.get_secret_value() if secret is not None else EMULATOR_CONNECTION


def client(**options: int) -> ServiceBusClient:
    return ServiceBusClient.from_connection_string(connection_string(), **options)
