"""The two capacity operations on HealthcareService: $board and $confirm-capacity (R05).

GET /fhir/HealthcareService/$board returns the wall board and exec read model as a Parameters
resource (QueryBoard, U08). It is never cached and holds no patient data. Roles: wall, advisor,
clinical, lead, exec, owner. Any other role is refused with the not-found answer (DEC-086 item 5).

POST /fhir/HealthcareService/{id}/$confirm-capacity says the figure on record is still right
(ConfirmCapacity, U02). Roles: a reporter for their own service, or a lead. It needs an
Idempotency-Key. The request body is not read: the service comes from the path and the actor from
the token, never from the body (DEC-145). A third confirmation in a row, or a service with no figure
to confirm, is 409 business-rule "Send the number for <service name>.".

The routes hold no business rule: they check the role and the service scope, run one use case and
map the result.
"""

from typing import Annotated, Final

from fastapi import APIRouter, Depends, Path, Request
from fastapi.responses import Response

from diucs.adapters.inbound.fhir_rest.app import get_container
from diucs.adapters.inbound.fhir_rest.auth import ensure_can_act_for, require_role
from diucs.adapters.inbound.fhir_rest.capability import FhirJSONResponse
from diucs.adapters.inbound.fhir_rest.concurrency import idempotency_key, replay_or_run
from diucs.adapters.inbound.fhir_rest.errors import operation_outcome
from diucs.adapters.inbound.fhir_rest.mapping import board_to_parameters, report_to_fhir
from diucs.application.actor import Actor
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.use_cases.confirm_capacity import ConfirmCapacity, ConfirmCapacityCommand
from diucs.application.use_cases.query_board import QueryBoard, QueryBoardQuery
from diucs.domain.codes import ReportSource, Role
from diucs.domain.errors import ConfirmLimitReached, NothingToConfirm

BOARD_ROLES: Final = (Role.WALL, Role.ADVISOR, Role.CLINICAL, Role.LEAD, Role.EXEC, Role.OWNER)
CONFIRM_ROLES: Final = (Role.REPORTER, Role.LEAD)
_SERVICE_ID: Final = r"^[A-Za-z0-9.\-]{1,64}$"

router = APIRouter(prefix="/fhir/HealthcareService")


class _UnitOfWorkIdempotency:
    """The idempotency store for ConfirmCapacity's early replay check, on the application's own
    unit of work, so this adapter needs no outbound adapter. The authoritative check and the write
    of the key are inside the use case's unit of work."""

    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def get(self, key: str) -> object | None:
        async with self._uow_factory() as uow:
            return await uow.idempotency.get(key)

    async def put(self, key: str, result: object) -> None:
        async with self._uow_factory() as uow:
            await uow.idempotency.put(key, result)
            await uow.commit()


@router.get("/$board")
async def board(
    request: Request, actor: Annotated[Actor, Depends(require_role(*BOARD_ROLES))]
) -> Response:
    container = get_container(request)
    result = await QueryBoard(container.uow_factory, container.clock).execute(
        QueryBoardQuery(actor=actor)
    )
    return FhirJSONResponse(
        content=board_to_parameters(result), headers={"Cache-Control": "no-store"}
    )


async def _send_the_number(uow_factory: UnitOfWorkFactory, service_id: str) -> Response:
    async with uow_factory() as uow:
        profile = await uow.services.get(service_id)
    text = "Send the number." if profile is None else f"Send the number for {profile.name}."
    return operation_outcome(409, "business-rule", text)


@router.post("/{service_id}/$confirm-capacity")
async def confirm_capacity(
    service_id: Annotated[str, Path(pattern=_SERVICE_ID)],
    request: Request,
    actor: Annotated[Actor, Depends(require_role(*CONFIRM_ROLES))],
) -> Response:
    ensure_can_act_for(actor, service_id)
    key = idempotency_key(request)
    container = get_container(request)

    async def run() -> Response:
        use_case = ConfirmCapacity(
            container.uow_factory,
            container.clock,
            container.ids,
            _UnitOfWorkIdempotency(container.uow_factory),
        )
        # A lead confirms for the service after phoning it; a reporter confirms from the app.
        source = ReportSource.ADVISOR_PHONED if actor.role is Role.LEAD else ReportSource.APP
        try:
            result = await use_case.execute(
                ConfirmCapacityCommand(
                    idempotency_key=key, actor=actor, service_id=service_id, source=source
                )
            )
        except ConfirmLimitReached, NothingToConfirm:
            return await _send_the_number(container.uow_factory, service_id)
        async with container.uow_factory() as uow:
            report = await uow.capacity.get(result.report_id)
        if report is None:
            raise RuntimeError("the confirmation that was just stored cannot be read")
        return FhirJSONResponse(content=report_to_fhir(report))

    # The cache name carries the operation and the service, so one key sent for two services is
    # not answered from the first one's response; the use case then refuses it as a Conflict.
    return await replay_or_run(request, actor, f"confirm-capacity:{service_id}:{key}", run)
