# Multi-tenancy and networks

Contents: the requirement, the model, the rules every task follows, what is never shared, the superseded transitional rule (history only), testing and evidence, hazards, the decisions that are yours and what can leave you stuck, where the detail lives.

The original specifications describe one deployment for one organisation. The owner has ruled that the platform is multi-tenant, with organisations collaborating in a network. The repo specs, plan and prompts are updated to match as the tenancy tasks land (they are yours to keep current, DEC-133). Until each is updated, these decisions override it:

- **DEC-130**: the platform is multi-tenant; the tenant is bound at one execution point.
- **DEC-131**: SMS and email are one Twilio subaccount per tenant; the number called identifies the tenant.
- **DEC-132**: tenant is the legal entity; a Network groups tenants; sharing is by grants and read-only projections.

Read all three in `docs/delivery/decisions.md` before any task that reads or writes data, sends or receives a message, shows capacity, or authenticates a person. The audit that prices the retrofit is in `docs/delivery/tenancy-audit/` (graph, application, adapters, front end, tests, lifecycle, task sweep); the master plan and the tenancy task ids come from it.

## The model in brief

1. **Tenant = a legal entity** (one organisation that feeds the platform). It is the data controller for its own data. Nothing in one tenant's scope is ever readable by another tenant.
2. **Every node carries `tenantId`.** This includes the nodes the mapper writes as fragments and version copies. A relationship belongs to the tenant of the nodes it joins and never joins nodes of two scopes.
3. **One binding point.** The tenant is bound once per unit of work, from a verified source only: the signed bearer token or BFF session for requests; validated message properties for workers; the number called (and `AccountSid`) for inbound SMS (DEC-131); the token hash for a link; the pairing for a wall screen. Never from a request body, a query string or any header the caller controls.
4. **`run_query`** (`adapters/outbound/graph_store/driver.py`) is the only place application Cypher runs. It adds `tenant` to every call from the bound context, refuses to run when none is bound (fixed message, fails closed), and a caller cannot pass or override it.
5. **The predicate cannot be injected into Cypher text.** Every statement writes `tenantId: $tenant` on each node it matches, merges or creates. Registering a statement that does not name `tenantId: $tenant` on each node it matches, merges or creates is refused (DEC-440). The only statements without it are the global ones of `GLOBAL_QUERY_IDS` (the health ping, the tenant directory and the two whole-graph invariant counts of DEC-441), run through `run_global_query` and pinned by digest; migrations run through the migration runner.
6. **Uniqueness is composite** (`tenantId` plus the key). Booking references (four digits) are unique within a tenant. Idempotency keys, link-token hashes, outbox ids, the audit hash chain, Redis keys (`diucs:<tenant>:...`) and Service Bus messages are tenant-scoped.
7. **A service, person or record from another tenant reads as NotFound,** never Forbidden. Existence must not leak.
8. **Network and sharing (DEC-132).** A `Network` (owned by a lead organisation that is itself a tenant) groups member tenants through `NetworkMembership`. Data is shared only through a `Grant` (grantor tenant, network, scope, purpose, dates, approved by the grantor's admin and by the network owner). A projector reads a member's data inside the member's scope and writes an allowlisted copy into the network scope, recording `sourceTenantId`. Members read the network capacity view through a read-only use case bound to the network scope. A unit of work binds **exactly one scope**. No query ever spans two scopes.
9. **Two kinds of scope.** A tenant scope and a network scope are bound the same way. A user belongs to one tenant; staff of a member tenant see the network capacity view as well as their own. Reporters on phone and link see their own tenant only. A wall screen is paired to one tenant and shows the tenant board or the network board as its administrator chooses.
10. **Cross-tenant support and operator access** is a separate, explicit, audited privilege that no role holds yet. Do not build a back door for convenience.
11. **History stays.** When a tenant leaves a network its grants lapse and nothing new is projected; projections already written remain for audit, marked with the leave date.

## What is never shared across tenants

Reporters' names, phone numbers, devices, PINs, link tokens, communications, bookings, cases, audit entries, and any patient-level data. Today a projection may hold only: capacity status and figures with the as-of time and not-updated flag; service name, category, location, district coverage, opening hours and service-level contact; the current criteria version. The allowlist is enforced by the privacy guard (D17) and by a test, so no other field can enter a projection. A shared patient record and care coordination is a possible far-future purpose; it would need its own scope, purpose, data sharing agreement, sign-off and decision. Do not build toward it beyond the `scope` and `purpose` on a Grant.

## History: the transitional rule (superseded by TEN-030, DEC-440)

Superseded. Tenancy has been enforced since TEN-030 (DEC-440): the seam is delivered, the ratchet and every transitional path are gone, and the full rules of the model above and the testing section below apply to every task. The six items below are kept as history, so that older evidence and decisions that cite them can be read. They are not rules any more:

1. All Cypher is a registered `NamedQuery` run through `run_query`. No f-string Cypher except constant fragments. No Cypher outside `run_query` (migrations, health and the test wipe are the only exceptions).
2. Match by the entity's own key, never by label alone and never by a global id that two tenants could share (an `id` the application generates, a four-digit reference, a message id, a token hash). Where a statement does match that way, list it in the evidence under "Tenant-pending statements" with the query id.
3. Do not add a new global singleton, a global counter or a global unique key without recording it in the evidence and in a decision.
4. Take the tenant from the actor (not the request body) at the use-case boundary. New use cases that take an id from outside validate it against the actor's scope when the actor type carries one.
5. Cache keys, channels, queue names and message properties are built in one function, so the tenant can be added in one place.
6. Write down the cross-scope reads your task would need under DEC-132 (for example a board showing providers' capacity) in the evidence, so the network design can price them.

Once the seam is delivered and "tenancy enforced" is recorded, the full rules apply to every task: items 4 to 7 of the model, and the tests below.

## Testing and evidence (enforced since TEN-030, DEC-440)

- **Registration check:** a statement without `$tenant` cannot be registered (allowlist aside).
- **Generated two-tenant test** over the query registry: seed two tenants, run every statement as tenant A, assert it reads and changes nothing of tenant B's. A new statement is covered automatically.
- **Per-task cross-tenant test:** each use case, route, worker or screen the task adds has a test with two tenants showing that A cannot read, change, delete or even detect B's records (NotFound), and that the same key or reference in both tenants does not collide.
- **Predicate-removal mutant:** the verifier removes the tenant predicate from one of the task's statements and a test must fail.
- **Network tests, where relevant:** a grant approved by both sides projects; a grant ended by the grantor stops projecting; history stays after a member leaves; no field outside the allowlist ever enters a projection; a member sees the network view but not another member's private data.
- **Harness:** each run uses a unique tenant and `clean_graph` deletes only that tenant's nodes. Runs share one Neo4j. Schema-changing tests and container-lifecycle tests still run alone.
- **Evidence:** a "Tenant isolation" section in the evidence file (see the template). Register it with `delivery.py evidence <ID> --kind other --ref <section> --summary "tenant-isolation: <result>"` until the ledger has a dedicated kind.

Until the tenant-per-run harness exists, run tests that need Neo4j one at a time (a machine-wide lock). Parallel runs each started their own Neo4j, overloaded the machine and filled the disk; unit, architecture and front-end tests are unaffected. Since DEC-135 the harness also takes its own lock (`/tmp/diucs-neo4j-harness.lock`) before it starts a container, so two sessions can no longer run two containers at once; the manual `flock /tmp/diucs-neo4j-tests.lock` is a different file and still queues whole runs.

## Hazards multi-tenancy adds

Cross-tenant data leak; a message sent from the wrong tenant's number or to the wrong tenant's reporter; a wall screen showing the wrong tenant's or the wrong network's board; a projection that carries something it should not; a revoked grant that still projects; a stale projection read as live; support or operator access misused; a person confused about which tenant they are viewing. Each gets a row in `docs/delivery/hazard-log.md` with its control and the test that proves it. Every screen that can show more than one scope says clearly which scope and which organisation each row belongs to.

## Decisions that are yours, and what can leave you stuck

You decide, record and build: the data sharing agreement's reference and version in the model, controller and processor roles, which grant scopes exist, the projection allowlist, who may hold cross-tenant support access (DEC-134), and per-tenant thresholds. Describe their status truthfully ("prepared, not externally certified"); none of it blocks a task. The only thing that can leave you stuck is a real Twilio subaccount, number, sender registration or other credential or spend (DEC-131): build against a fake secret store and a recording sender, verify it, and list it as "needs a real credential at deploy".
