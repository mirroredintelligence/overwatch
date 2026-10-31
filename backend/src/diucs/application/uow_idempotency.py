"""The idempotency store of a use case's early replay check, on the application's own unit of work
(KI-35, KI-36, KI-149), so an inbound adapter needs no outbound adapter. The authoritative check and
the write of the key are inside the use case's own unit of work; this store only answers the early
read, and its `put` is for a use case that has no unit of its own to write in.

One class for the routes, the link pages and the worker: three copies had been written, and they
could drift apart.
"""

from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory


class UnitOfWorkIdempotency:
    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def get(self, key: str) -> object | None:
        async with self._uow_factory() as uow:
            return await uow.idempotency.get(key)

    async def put(self, key: str, result: object) -> None:
        async with self._uow_factory() as uow:
            await uow.idempotency.put(key, result)
            await uow.commit()
