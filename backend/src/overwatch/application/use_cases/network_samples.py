"""Recording the hourly sample of a network board (TEN-082, DEC-132 item 4).

The board projector calls `record` after it has built a board that is not from its cache (a rebuild
after an event, or a read that found no cached board): the counts of that board are filed under the
hour that holds it, in a unit of work bound to the network scope. It is system work, not a viewer's
write: the viewer's unit stays read-only, and a sample holds counts and a pressure level and nothing
else (`domain/rules/network_sample.py`).

A failure to record is the projector's to swallow (a board must never fail because its history
could not be written); here it is raised, so a test sees it.
"""

from diucs.application.ports.outbound.unit_of_work import NetworkUnitOfWorkFactory
from diucs.application.tenancy import bind_network
from diucs.application.use_cases.query_network_board import NetworkBoardView
from diucs.domain.rules.network_sample import sample_of


class RecordNetworkSample:
    def __init__(self, uow_factory: NetworkUnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def record(self, network_id: str, view: NetworkBoardView) -> None:
        sample = sample_of(view.board)
        with bind_network(network_id):
            async with self._uow_factory() as uow:
                await uow.network_samples.record(sample)
                await uow.commit()
