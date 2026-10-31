# Runbook: grant and sharing incidents

For the network owner's administrator, a member's administrator and the platform operator. A network shows only what a grant allows, projected by the platform into the network's own scope; a grant is the only way anything is shared and the grantor can end it at any time. Decisions: DEC-132, DEC-134 item 6, DEC-136 items 3 and 4, DEC-960 to DEC-967; hazards H-N01 to H-N15, H-630 to H-644.

## Stop sharing now

| I need to stop... | Do this | Takes effect |
|---|---|---|
| one kind of one member's data (capacity, directory or criteria) | the member's tenant administrator: `POST /network-admin/grants/{id}/end` | at once: the registry's gate closes before anything else; the network scope's source ends and its rows are marked with the date |
| everything one member shares | the member leaves (`POST /network-admin/network/{id}/leave`) or the owner removes it (`.../members/{membership}/remove`) | at once for the registry; the network scope follows in the same call |
| one service of a member | the owner suspends its listing (`.../listings/{id}/suspend`, with a reason code) or the member withdraws it | the producer stops building it; the board shows it unavailable |
| a whole tenant (a security incident) | the operator suspends it (`provision_tenant.py suspend`) | the edge within 60 seconds; its projections go stale and read "Not updated" |

Ending is never delayed for a record: if the call fails after the registry write, run the **same call again**; it finishes what is left and records nothing twice. Nothing is deleted: history stays (DEC-132 item 6).

## What a member can see of the network

Staff of a member tenant who may see the board see the network board, directory and criteria **of members that have an effective grant, an active membership and an admitted listing** (the rows are joined to the registry at the time of every read). A member that left is refused at once, not at token expiry. A reporter, a wall screen, an anonymous link, support, audit and the administrators never see a network board.

## Incidents

### A grant was ended but its data still shows

1. Read the grant: `GET /network-admin/grants` (member) or `GET /network-admin/network/{id}/grants` (owner): `status` should be `ended` and `effective` false.
2. If it is, the live read already leaves the member out (the registry decides). Look at `GET /network-admin/network/{id}/projection`: the kind should be `ended` with `end_reason`.
3. A kind still `active` is a lost step: the heartbeat's reconciliation ends it on its next run (within 5 minutes); to do it now, the grantor runs the end again. A member that left is also reconciled for 24 hours.
4. If a row is still shown after the registry says ended, **stop and report it as a privacy incident**: the live view must exclude it whatever the network scope holds.

### A projection holds something it should not

The network scope holds only the allowlist (DEC-132 item 4): service name, category, place (district, city, coordinates), opening hours, a service-level contact, the figures the status is computed from, the current criteria. Never a person, a reporter, a booking, a case, a communication or an audit entry. If anything else appears:

1. Suspend the member's listing and end its grants (above).
2. Report it to the information governance lead and the clinical safety officer at once (DCB0129 hazard log; a possible breach).
3. Do not edit the network scope by hand. The privacy guard and the allowlist tests (`tests/unit/application/test_projection_allowlist.py`, `tests/integration/graph_store/test_network_scope_isolation.py`) show where the leak got in.

### The network board is not updating, or shows a stale figure as current

- The board computes a status at the time of the read from the stored inputs, so a member that stops reporting turns "Not updated" with no event. If it does not, report it: that is hazard H-N03.
- A member whose figures stop moving: check its heartbeat (`projection_boundaries`): the member's scheduled work of kind `projection-heartbeat`; the producer needs an effective grant, an active membership and an admitted listing.
- A service that **has never appeared**: is its listing admitted (`GET .../listings`)? Is the grant of that kind approved by both sides and started (`effective` true)? A grant that starts later projects nothing until then.

### Two approvers are one person

The two approvals of a grant must come from two different accounts. When the grantor and the network owner are one organisation, two different people still have to approve. The records hold each approval's account reference (never a name). If a person holds both roles in two tenants, their references differ per tenant today (a known limit): ask the owner's administrator to confirm the second approver is a different person.

### A member is on an old agreement version

`GET /network-admin/networks` (member) and `.../members` (owner) show `agreement_behind`. A new version does not change what is shared; the member's administrator accepts it when ready. Widening what a grant shares needs a newer agreement version and a new grant version (`POST /network-admin/grants/{id}/revise`).

### A governance event failed

The events of the actions are on the acting tenant's outbox and reach the projector's governance consumer (`network.events`, subscription `network-projector`). A dead-lettered message (reasons: `message-invalid`, `not-found`, `sender-mismatch`) is a refusal, not a failure: check the grant or network named in the registry. A retry that repeats names only the class of the error: check Neo4j and the registry. Every step is repeatable.

## After any incident

Record what you did and why in the incident ticket by id (grant, membership, listing), never with a person's data. The network's audit chain and the acting tenant's chain already hold each action with its actor's reference.
