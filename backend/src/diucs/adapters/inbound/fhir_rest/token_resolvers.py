"""Token resolvers for routes that carry no signed token (TEN-041, DEC-520). Stub for red."""

from typing import Annotated

from fastapi import Depends, Request

from diucs.adapters.inbound.fhir_rest.host_tenant import bind_host_tenant
from diucs.application.tenant_resolution import PreSessionResolver
from diucs.domain.model.device import Device
from diucs.domain.model.tenant import Tenant


def pre_session_resolver(request: Request) -> PreSessionResolver:
    raise NotImplementedError


def bearer_token(request: Request) -> str:
    raise NotImplementedError


async def resolve_active_device(
    request: Request, tenant: Annotated[Tenant, Depends(bind_host_tenant)]
) -> Device:
    raise NotImplementedError
