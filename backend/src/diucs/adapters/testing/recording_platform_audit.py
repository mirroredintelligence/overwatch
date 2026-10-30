"""Recording stand-in for the platform audit chain (TEN-084): keeps every entry in order and can be
told to fail the next append, so a test can show that an access never stands without its record."""

from diucs.application.ports.outbound.platform_audit import PlatformAuditEntry


class RecordingPlatformAudit:
    def __init__(self) -> None:
        self.entries: list[PlatformAuditEntry] = []
        self.fail_next = False

    async def append(self, entry: PlatformAuditEntry) -> None:
        if self.fail_next:
            self.fail_next = False
            raise ConnectionError("platform audit is down")
        self.entries.append(entry)
