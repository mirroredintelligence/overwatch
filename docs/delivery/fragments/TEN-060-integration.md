# TEN-051 to TEN-060: the network chain run for the first time (fix bundle F5C)

All the network integration files were written and never run. They now run green, serially and
under `-n 4` on the shared Neo4j. No product bug was found; every failure was a test, fixture or
harness cause. No isolation or privacy finding in the product (the leak candidates the tests look
for, a tenant id or grant id in a result, a tenant property on a network node, a cross-scope
relationship, a poison value in the network scope, were all clean once the worlds were built).

## Causes and fixes (all in tests and `tests/support`)

1. **A seeded world was wiped by `clean_graph`.** The conftest appends `clean_graph` to the end of a
   test's fixtures, so the `world` fixtures built their data and the wipe then deleted the network
   record (35 errors "the network was not found"). The four `world` fixtures now depend on
   `clean_graph` (lesson L84).
2. **The registry carries no tenant, and the tests deleted all of it.** `REGISTRY_CLEAN` and
   `NetworkWorld.cleanup` ran `MATCH (n) WHERE n:Network OR n:NetworkMembership OR n:Grant OR
   n:Listing DETACH DELETE n`, which on the shared Neo4j deletes other runs' networks. They now call
   `wipe_tenant` for the run's own network ids, and `wipe_tenant` also deletes the
   `NetworkMembership`, `Grant` and `Listing` records that name the network as `networkId`.
3. **Registry keys are unique across the database, and the samples used fixed ids** (`net-pilot`,
   `grant-b-capacity`, `lst-b-1`, `mem-owner`, `tenant-a`). `tests/support/network_samples.py` now
   derives the network, owner, members and outsider from the run's scope ids and adds `rid()` (the
   run token) to record ids; outside pytest the readable names stay. Two workers on one Neo4j no
   longer collide (`-n 4` run).
4. **A sample criteria row names a predecessor that does not exist** (`supersedes_id='crit-0'`); the
   repository refuses it. The seeds in the network worlds pass `supersedes_id=None`.
5. **The world named a listing after the tenant** (`lst-<tenant>`), and the result shows the row
   reference, so a test that looks for a tenant id in a result found one. A listing id now carries
   the run and the member number only. (Product ids are generated; nothing in `src` builds an id
   from a tenant.)
6. **The projection allowlist test scanned the scope stamp as a forbidden key.** `tenantId` is a
   system property of every node (and on the permitted list); the scan now covers the non-system
   properties as keys and values, and the system properties as values.
7. **`REDIS_URL` was read with `os.environ[...]`;** the other tests default to localhost.
8. **A token past its expiry** in `test_network_view` (the app's clock is late October 2026, the
   default test token expires 24 October): the test issues a token that outlives the world's clock.
9. **A board cached for a minute by an earlier test of the same worker** (same network id) was served
   to the next test: the `cache` and `app` fixtures delete the run network's cached board before and
   after.
10. **The whole-database invariant check on a shared Neo4j** counts other runs' and old nodes
    (5 unstamped `TestMark` nodes from an older test). Its assertion moved to
    `test_network_scope_global_invariants.py`, which runs on a private container (`schema`) and also
    covers a member leaving. The scope-wise invariants stay in `test_network_scope_isolation.py`.
11. **Migrations tests expected the contract step last.** `0110_network_registry` and
    `0111_projection_keys` sort after `0105_drop_superseded_keys` by design (TEN-051); the pinned id
    list and the "second run" test say so, and `Listing` is a registry label in the single-key test.
12. **The emulator ran the owner checkout's older `servicebus-config.json`**
    (no `projection.work`, no `network-projector` subscriptions, no `network.events`, no channel
    rules). See TEN-055-integration.md.

## Known issues (one line each, with triggers)

| Task | Issue | Where | Trigger |
|---|---|---|---|
| TEN-054 | The integration worlds call `ensure_audit_head` for the network scope; no product start-up provisions a network's audit chain head | `tests/support/network_world.py` | Before a network is created in production (the network create use case) |
| TEN-056 | Reconciliation and governance events are not built | `domain/events.py` | TEN-056 |
| TEN-054 | A rejected projection is not audited | `use_cases/apply_projection.py` | If the owner wants rejected attempts in the chain |
| TEN-059 | `create_app` has no production caller that sets `app.state.network_services` | `adapters/inbound/fhir_rest/app.py` | The composition root of the network routes |
| TEN-060 | `tests/integration/test_infra_up.py` expects the whole owner compose stack including Neo4j under one compose project; with the shared-test layout (`diucs-b3sb` has Redis and Service Bus only) three of its tests need `COMPOSE_PROJECT_NAME=diucs-b3sb` and a Neo4j service started there | `tests/integration/test_infra_up.py` | A run on a machine with no owner stack |
