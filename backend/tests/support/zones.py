"""A tenant zone source for tests that need a zone other than Europe/London.

The allow-list of tenant zones holds only Europe/London today, so the registry cannot hold another
zone yet; the rules and the use cases take any `ZoneInfo`, and these tests show that the one the
tenant's source gives is the one used."""

from zoneinfo import ZoneInfo

from overwatch.application.tenancy import ScopeId

NEW_YORK = ZoneInfo("America/New_York")


class FixedZones:
    """The same zone for every tenant, and the scopes it was asked about."""

    def __init__(self, zone: ZoneInfo = NEW_YORK) -> None:
        self._zone = zone
        self.asked: list[ScopeId] = []

    async def zone_of(self, scope: ScopeId) -> ZoneInfo:
        self.asked.append(scope)
        return self._zone
