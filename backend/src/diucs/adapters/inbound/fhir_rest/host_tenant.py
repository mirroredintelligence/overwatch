"""Tenant resolution from the request host for routes with no token (TEN-040). Stub."""

from collections.abc import AsyncIterator

from fastapi import Request

from diucs.domain.errors import NotFound
from diucs.domain.model.tenant import Tenant


class HostNotResolved(NotFound):
    pass


def request_host(request: Request) -> str | None:
    raise NotImplementedError


async def resolve_request_tenant(request: Request) -> Tenant | None:
    raise NotImplementedError


async def bind_host_tenant(request: Request) -> AsyncIterator[Tenant]:
    raise NotImplementedError
    yield  # pragma: no cover
