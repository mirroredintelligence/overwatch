# Milestones (DEC-143)

## M1: two-tenant vertical slice

A reporter sends a capacity figure by text. It is received, stored and shown on the wall board. Two tenants do this at once, each seeing only its own services, on real Neo4j. It proves the core loop and tenant isolation together. Networks and the cross-tenant projection come after M1 (DEC-132).

Done when: an end-to-end test sends a text to tenant A's number and a text to tenant B's number, each with the same service key and booking reference, and each wall board shows only its own figure. The generated two-tenant test (TEN-004) passes for every statement the slice uses, and enforce mode (TEN-030) is on. As of TEN-004 the test is built and proves 8 starter statements (credential, outbox and processed-marker); the slice's own statements (the capacity lock, trailing confirms, latest-confirmed-at, the service reads) are NOT converted yet, because they match nodes the resource store writes without a tenant. They convert after TEN-009 (resource store stamped and anchored) and TEN-010 (service and capacity repositories). Statements that cannot be proved with colliding keys wait for TEN-005 (composite constraints).

## How work is bundled

A bundle is a chain of tasks that one builder session claims and builds in order, and one verifier session verifies in a single pass. The ledger is unchanged: each task still has its own claim, evidence rows and verify record. This removes the per-task cost of starting an agent, reading the skill and re-establishing the worktree. A bundle gets one verification round, and at most two (DEC-141). Builders run at most three at a time.

| Bundle | Tasks (in order) | Needs | Notes |
|---|---|---|---|
| B1 Seam | TEN-001, TEN-002, TEN-003, TEN-004, TEN-005 | G01, G14, P06, F10b | The registry seam (DEC-142), the unit of work on the scoped transaction, tenant-per-run harness, the generated two-tenant test, composite constraints. TEN-005 runs alone. |
| B2 Tenant core | TEN-006, TEN-007, TEN-008, TEN-009 | B1 | Pure tenant model, the tenant directory and secret references, the mapper and resource store stamped and anchored. |
| B3 Stores | TEN-010, TEN-011, TEN-012, TEN-015, TEN-016 | B2 | Service, capacity, booking, case, person, scope-list, criteria, flag, communication, scheduled-work, outbox, idempotency repositories. One module family at a time. |
| B4 Audit, cache and bus | TEN-017, TEN-019, TEN-020, TEN-025 | B1, B3 | Audit chain per scope, cache keys and channels, the Service Bus tenant property, the consumer binding the tenant. |
| B5 Edge and rules | TEN-018, TEN-021, TEN-024, TEN-039, TEN-040, TEN-041 | B2, B3, B4 | REST edge and Actor, tenant policy in the rules, ReportCapacity rework, board projector, host and inbound-number resolution. |
| B6 Enforce | TEN-030 | B1 to B5 | Enforce mode on, the ratchet empty, mutant evidence. |
| B7 Slice | I07, U05, R05, W05 (and U10, R15, W08 for pairing) | B5 | The inbound webhook, the capacity reply handler, `$board`, the wall board page. These can start before the bundles above finish: they follow the transitional rule (`references/multi-tenancy.md`) and are retrofitted by the bundles. |

## Order and parallelism

1. Now: B1 (TEN-001 first), U03 finish, and the B7 tasks that do not depend on tenancy (R05, then W05; I07 and U05 as builder slots free).
2. After B1: B2, then B3 and B4 in parallel (they touch different modules; Neo4j tests still run one directory at a time under the lock).
3. Then B5, B6, and the slice end-to-end test.
4. After M1: the other S4 to S9 stages and the network tasks (TEN-036 onward), in the order the plan gives.

## After M1

Networks and grants (TEN-036 to TEN-062), the front-end tenancy work (TEN-044 to TEN-050), lifecycle and administration (TEN-028, TEN-073 to TEN-084), and the end-to-end suite (TEN-085) follow, as their own bundles.

## Required before any real use of the wall board

W05 shows a snapshot that does not refresh, and a stale `generatedAt` only shows an old clock (hazard H-33, verifier note). A wall must not be relied on until **W06** (live updates and Last known) and the stale rule it implements are delivered. W06 is therefore part of M1, not after it.

