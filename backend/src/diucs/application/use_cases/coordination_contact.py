"""The tenant's coordination phone, for the board (W7A-B8, DEC-777).

The number the duty coordinator is called on is an organisational role number held in the tenant's
configuration (a TenantContact of kind coordination-phone, never a person's). It is read inside the
tenant's own unit of work, so another tenant's number is never returned. A tenant with none has
none: no number is made up (H-T15).
"""

from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.domain.model.tenant import ContactKind


class ReadCoordinationPhone:
    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def execute(self) -> str | None:
        async with self._uow_factory() as uow:
            contacts = await uow.tenant_config.contacts()
        return next(
            (c.value for c in contacts if c.kind is ContactKind.COORDINATION_PHONE),
            None,
        )
