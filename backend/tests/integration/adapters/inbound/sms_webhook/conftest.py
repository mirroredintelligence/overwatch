"""Fixtures for the Twilio webhook tests (I07): the FHIR app with the webhook's collaborators set,
the real Neo4j of the harness for the allow-list, and a recording bus and cache (external
providers only)."""

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from neo4j import AsyncDriver, AsyncManagedTransaction

from diucs.adapters.inbound.sms_webhook.routes import SmsWebhookDeps
from diucs.adapters.outbound.graph_store.person_repository import Neo4jPersonRepository
from diucs.adapters.outbound.graph_store.resource_store import ResourceStore
from diucs.adapters.testing.memory_cache import InMemoryCache
from diucs.adapters.testing.memory_event_bus import ManualEventBus
from diucs.application.ports.outbound.identity import HmacPhoneHasher
from diucs.bootstrap.container import Container
from diucs.domain.model.people import Practitioner
from tests.support.api import api_app, test_container
from tests.support.neo4j import write_tx
from tests.support.sms import (
    PUBLIC_BASE_URL,
    SENDER_E164,
    inbound_lines,
    phone_hash,
    secret_store,
)

__all__ = [
    "api_app",
    "test_container",
    "sms_bus",
    "sms_cache",
    "sms_app",
    "sms_client",
    "reporter",
    "seed_practitioner",
]


async def seed_practitioner(driver: AsyncDriver, practitioner_id: str, number: str) -> None:
    person = Practitioner(
        id=practitioner_id,
        active=True,
        display_name=f"Reporter {practitioner_id}",
        phone_hash=phone_hash(number),
    )

    async def work(tx: AsyncManagedTransaction) -> None:
        await Neo4jPersonRepository(tx, ResourceStore(tx)).save_practitioner(person)

    await write_tx(driver, work)


@pytest.fixture
def sms_bus(test_container: Container) -> ManualEventBus:
    return ManualEventBus(test_container.clock)


@pytest.fixture
def sms_cache(test_container: Container) -> InMemoryCache:
    return InMemoryCache(test_container.clock)


@pytest.fixture
def sms_app(api_app: FastAPI, sms_bus: ManualEventBus, sms_cache: InMemoryCache) -> FastAPI:
    secrets = secret_store()
    api_app.state.sms_webhook = SmsWebhookDeps(
        cache=sms_cache,
        event_bus=sms_bus,
        hasher=HmacPhoneHasher(secrets),
        secrets=secrets,
        lines=inbound_lines(),
        public_base_url=PUBLIC_BASE_URL,
    )
    return api_app


@pytest_asyncio.fixture
async def sms_client(sms_app: FastAPI) -> AsyncIterator[AsyncClient]:
    # The request reaches the app as http://internal:8000, as it would behind a proxy.
    async with AsyncClient(
        transport=ASGITransport(app=sms_app, raise_app_exceptions=False),
        base_url="http://internal:8000",
    ) as client:
        yield client


@pytest_asyncio.fixture
async def reporter(neo4j_driver: AsyncDriver) -> None:
    """One active practitioner whose phone hash is the sample sender's (07700 900123)."""
    await seed_practitioner(neo4j_driver, "p-reporter-1", SENDER_E164)
