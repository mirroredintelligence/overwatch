"""Fake inbound-line directory: a fixed map of numbers to tenants (I07, DEC-131).

An external-provider fake: the real directory is the tenant directory of TEN-007, and TEN-041 plugs
its inbound-number resolver into the InboundLineDirectory port. A number matches only together with
its own account, and an account belongs to one tenant.
"""

from collections.abc import Iterable

from diucs.application.ports.outbound.tenant_lines import InboundLine


class FixedInboundLines:
    def __init__(self, lines: Iterable[tuple[str, str, InboundLine]]) -> None:
        self._by_number: dict[tuple[str, str], InboundLine] = {}
        self._by_account: dict[str, InboundLine] = {}
        for number, account_sid, line in lines:
            known = self._by_account.get(account_sid)
            if known is not None and known.tenant_id != line.tenant_id:
                raise ValueError("an account belongs to one tenant")
            self._by_number[(number, account_sid)] = line
            self._by_account[account_sid] = line

    async def for_number(self, to_number: str, account_sid: str) -> InboundLine | None:
        return self._by_number.get((to_number, account_sid))

    async def for_account(self, account_sid: str) -> InboundLine | None:
        return self._by_account.get(account_sid)
