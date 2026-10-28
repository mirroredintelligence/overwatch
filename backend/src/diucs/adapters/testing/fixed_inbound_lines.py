"""Fake inbound-line directory: a fixed map of numbers to tenants (I07). Stub for the red run."""

from collections.abc import Iterable

from diucs.application.ports.outbound.tenant_lines import InboundLine


class FixedInboundLines:
    def __init__(self, lines: Iterable[tuple[str, str, InboundLine]]) -> None:
        self._lines = list(lines)

    async def for_number(self, to_number: str, account_sid: str) -> InboundLine | None:
        return InboundLine("stub", "stub")

    async def for_account(self, account_sid: str) -> InboundLine | None:
        return InboundLine("stub", "stub")
