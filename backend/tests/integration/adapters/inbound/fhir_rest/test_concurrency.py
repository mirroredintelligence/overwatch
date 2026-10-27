"""FHIR concurrency over HTTP (R03): ETag on reads, If-Match on writes, Idempotency-Key on creates.

Runs through api_client on the harness Neo4j (DEC-004). The routes below are test-only and write
:TestThing nodes through a real unit of work. Every request carries a synthetic bearer token.
"""

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

import pytest
from fastapi import Depends, FastAPI, Request, Response
from httpx import AsyncClient

from diucs.adapters.inbound.fhir_rest.auth import BFF_SECRET_NAME, current_actor
from diucs.adapters.inbound.fhir_rest.capability import FhirJSONResponse
from diucs.adapters.inbound.fhir_rest.concurrency import (
    check_version,
    idempotency_key,
    replay_or_run,
    require_if_match,
    scoped_key,
    subject_of,
    versioned_response,
)
from diucs.adapters.outbound.graph_store.unit_of_work import Neo4jUnitOfWork
from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.adapters.testing.memory_cache import InMemoryCache
from diucs.adapters.testing.tokens import TEST_BFF_SECRET, issue_test_token
from diucs.application.actor import Actor
from diucs.domain.codes import Role
from diucs.domain.errors import NotAllowed, NotFound
from tests.support.things import THING_FACTORIES, as_things

LONG_EXPIRY = datetime(2026, 11, 30, 12, 0, tzinfo=UTC)
PATH = "/fhir/test/things"
BODY: dict[str, str] = {"resourceType": "TestThing", "note": "synthetic"}
OTHER_BODY: dict[str, str] = {"resourceType": "TestThing", "note": "another synthetic"}


def bearer(sub: str, role: Role = Role.LEAD) -> dict[str, str]:
    token = issue_test_token(role, [], sub, expires_at=LONG_EXPIRY)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def things_app(api_app: FastAPI, test_container: Any) -> FastAPI:
    api_app.state.secrets = FixedSecretStore({BFF_SECRET_NAME: TEST_BFF_SECRET})
    api_app.state.cache = InMemoryCache(test_container.clock)
    api_app.state.runs = []

    def things_uow() -> Neo4jUnitOfWork:
        return Neo4jUnitOfWork(test_container.neo4j, THING_FACTORIES, test_container.clock)

    api_app.state.things_uow = things_uow

    @api_app.get(PATH + "/{thing_id}")
    async def read_thing(
        thing_id: str, request: Request, actor: Annotated[Actor, Depends(current_actor)]
    ) -> Response:
        async with request.app.state.things_uow() as uow:
            version = await as_things(uow.things).version_of(thing_id)
        if version is None:
            raise NotFound("thing")
        return versioned_response({"resourceType": "TestThing", "id": thing_id}, version_id=version)

    @api_app.put(PATH + "/{thing_id}")
    async def update_thing(
        thing_id: str,
        request: Request,
        expected: Annotated[int, Depends(require_if_match)],
        actor: Annotated[Actor, Depends(current_actor)],
    ) -> Response:
        async with request.app.state.things_uow() as uow:
            things = as_things(uow.things)
            current = await things.lock_and_version(thing_id)
            if current is None:
                raise NotFound("thing")
            check_version(expected, current)
            await things.bump(thing_id, current + 1)
            await uow.commit()
        return versioned_response(
            {"resourceType": "TestThing", "id": thing_id}, version_id=current + 1
        )

    @api_app.post(PATH)
    async def create_thing(
        request: Request,
        actor: Annotated[Actor, Depends(current_actor)],
        key: Annotated[str, Depends(idempotency_key)],
    ) -> Response:
        sub = subject_of(actor)

        async def run() -> Response:
            request.app.state.runs.append("post")
            async with request.app.state.things_uow() as uow:
                # The durable guard (P15) inside the unit of work: it outlives the cache entry.
                if await uow.idempotency.get(scoped_key(sub, key)) is not None:
                    return FhirJSONResponse({"created": False}, status_code=201)
                thing_id = f"t-{len(request.app.state.runs)}-{sub}"
                await as_things(uow.things).create(thing_id)
                await uow.idempotency.put(scoped_key(sub, key), actor)
                await uow.commit()
            return FhirJSONResponse({"created": True, "id": thing_id}, status_code=201)

        return await replay_or_run(request, sub, key, run)

    @api_app.post(PATH + "/refused")
    async def refused_thing(
        request: Request,
        actor: Annotated[Actor, Depends(current_actor)],
        key: Annotated[str, Depends(idempotency_key)],
    ) -> Response:
        sub = subject_of(actor)

        async def run() -> Response:
            request.app.state.runs.append("refused")
            raise NotAllowed("role")

        return await replay_or_run(request, sub, key, run)

    return api_app


async def seed(app: FastAPI, thing_id: str, version: int) -> None:
    async with app.state.things_uow() as uow:
        things = as_things(uow.things)
        await things.create(thing_id)
        await things.bump(thing_id, version)
        await uow.commit()


async def version_of(app: FastAPI, thing_id: str) -> int | None:
    async with app.state.things_uow() as uow:
        return await as_things(uow.things).version_of(thing_id)


async def things_in_graph(app: FastAPI) -> int:
    async with app.state.things_uow() as uow:
        return await as_things(uow.things).count()


def put(client: AsyncClient, thing_id: str, sub: str, if_match: str | None) -> Any:
    headers = bearer(sub)
    if if_match is not None:
        headers["If-Match"] = if_match
    return client.put(f"{PATH}/{thing_id}", json=BODY, headers=headers)


def post(client: AsyncClient, sub: str, key: str | None, body: dict[str, str] = BODY) -> Any:
    headers = bearer(sub)
    if key is not None:
        headers["Idempotency-Key"] = key
    return client.post(PATH, json=body, headers=headers)


def error_code(response: Response) -> str:
    return str(response.json()["issue"][0]["code"])


# 1. Reads carry the version as a weak ETag.
async def test_a_read_returns_the_version_as_a_weak_etag(
    things_app: FastAPI, api_client: AsyncClient
) -> None:
    await seed(things_app, "t-read", 3)
    response = await api_client.get(f"{PATH}/t-read", headers=bearer("pr-1"))
    assert response.status_code == 200
    assert response.headers["ETag"] == 'W/"3"'
    assert response.json()["meta"]["versionId"] == "3"


# 2. Updates need the current version in If-Match.
async def test_a_put_with_no_if_match_is_428_and_changes_nothing(
    things_app: FastAPI, api_client: AsyncClient
) -> None:
    await seed(things_app, "t-428", 3)
    response = await put(api_client, "t-428", "pr-1", None)
    assert response.status_code == 428
    assert error_code(response) == "required"
    assert await version_of(things_app, "t-428") == 3


async def test_a_put_with_a_stale_version_is_412_and_changes_nothing(
    things_app: FastAPI, api_client: AsyncClient
) -> None:
    await seed(things_app, "t-412", 3)
    response = await put(api_client, "t-412", "pr-1", 'W/"2"')
    assert response.status_code == 412
    assert error_code(response) == "conflict"
    assert await version_of(things_app, "t-412") == 3


async def test_a_put_with_the_current_version_runs_and_stores_version_4(
    things_app: FastAPI, api_client: AsyncClient
) -> None:
    await seed(things_app, "t-ok", 3)
    response = await put(api_client, "t-ok", "pr-1", 'W/"3"')
    assert response.status_code == 200
    assert response.headers["ETag"] == 'W/"4"'
    assert await version_of(things_app, "t-ok") == 4


async def test_a_put_with_a_malformed_if_match_is_412(
    things_app: FastAPI, api_client: AsyncClient
) -> None:
    await seed(things_app, "t-bad", 3)
    response = await put(api_client, "t-bad", "pr-1", '"3"')
    assert response.status_code == 412
    assert await version_of(things_app, "t-bad") == 3


# 3. Creates need an Idempotency-Key.
async def test_a_post_with_no_idempotency_key_is_400_and_creates_nothing(
    things_app: FastAPI, api_client: AsyncClient
) -> None:
    response = await post(api_client, "pr-1", None)
    assert response.status_code == 400
    assert error_code(response) == "required"
    assert things_app.state.runs == []
    assert await things_in_graph(things_app) == 0


async def test_a_post_with_an_invalid_idempotency_key_is_400_invalid(
    things_app: FastAPI, api_client: AsyncClient
) -> None:
    response = await post(api_client, "pr-1", "has a space")
    assert response.status_code == 400
    assert error_code(response) == "invalid"
    assert things_app.state.runs == []


# 4 and 5. The same key and body runs once; a different body is refused.
async def test_two_posts_with_the_same_key_and_body_run_the_handler_once(
    things_app: FastAPI, api_client: AsyncClient
) -> None:
    first = await post(api_client, "pr-1", "key-4")
    second = await post(api_client, "pr-1", "key-4")
    assert first.status_code == 201
    assert second.status_code == 201
    assert second.headers["Idempotent-Replay"] == "true"
    assert second.content == first.content
    assert things_app.state.runs == ["post"]
    assert await things_in_graph(things_app) == 1


async def test_the_same_key_with_another_body_is_422_and_adds_no_node(
    things_app: FastAPI, api_client: AsyncClient
) -> None:
    await post(api_client, "pr-1", "key-5")
    second = await post(api_client, "pr-1", "key-5", OTHER_BODY)
    assert second.status_code == 422
    assert error_code(second) == "conflict"
    assert await things_in_graph(things_app) == 1


# 6. The key is per subject.
async def test_the_same_key_from_two_subjects_runs_both(
    things_app: FastAPI, api_client: AsyncClient
) -> None:
    await post(api_client, "pr-1", "key-6")
    await post(api_client, "pr-2", "key-6")
    assert things_app.state.runs == ["post", "post"]
    assert await things_in_graph(things_app) == 2


# 7. After the cache entry expires, the durable store stops a second node.
async def test_after_24_hours_the_durable_store_stops_a_second_node(
    things_app: FastAPI, api_client: AsyncClient, test_container: Any
) -> None:
    await post(api_client, "pr-1", "key-7")
    test_container.clock.advance(timedelta(hours=24) - timedelta(seconds=1))
    within = await post(api_client, "pr-1", "key-7")
    assert within.headers["Idempotent-Replay"] == "true"
    assert things_app.state.runs == ["post"]
    test_container.clock.advance(timedelta(seconds=2))
    again = await post(api_client, "pr-1", "key-7")
    assert again.status_code == 201
    assert things_app.state.runs == ["post", "post"]
    assert await things_in_graph(things_app) == 1


# Guards that need their own case (lesson L135).
async def test_a_refused_create_is_not_cached_so_a_retry_runs_again(
    things_app: FastAPI, api_client: AsyncClient
) -> None:
    headers = {**bearer("pr-1"), "Idempotency-Key": "key-r"}
    first = await api_client.post(PATH + "/refused", json=BODY, headers=headers)
    second = await api_client.post(PATH + "/refused", json=BODY, headers=headers)
    assert first.status_code == 404
    assert second.status_code == 404
    assert "Idempotent-Replay" not in second.headers
    assert things_app.state.runs == ["refused", "refused"]


async def test_a_missing_cache_is_an_unexpected_error_and_the_handler_does_not_run(
    things_app: FastAPI, api_client: AsyncClient
) -> None:
    things_app.state.cache = None
    response = await post(api_client, "pr-1", "key-c")
    assert response.status_code == 500
    assert things_app.state.runs == []


async def test_a_post_with_no_token_is_401_before_any_write(
    things_app: FastAPI, api_client: AsyncClient
) -> None:
    response = await api_client.post(PATH, json=BODY, headers={"Idempotency-Key": "key-n"})
    assert response.status_code == 401
    assert things_app.state.runs == []


async def test_the_stored_replay_holds_a_hash_of_the_request_not_the_request(
    things_app: FastAPI, api_client: AsyncClient
) -> None:
    await post(api_client, "pr-1", "key-h")
    stored = await things_app.state.cache.get("idem:pr-1:key-h")
    assert stored is not None
    assert "synthetic" not in stored
