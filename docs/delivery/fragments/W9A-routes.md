# W9A routes: the network and grant administration API (TEN-079)

For the front-end bundles that follow (TEN-080, TEN-081). Back-end code: `backend/src/diucs/adapters/inbound/fhir_rest/routes_network_admin.py`; tests: `backend/tests/integration/adapters/inbound/fhir_rest/test_network_admin_routes.py` (the role matrix over all thirteen roles, two tenants, and a whole flow on a real graph).

## Mount and rules

- Every path is at the app **root** under `/network-admin` (not under `/fhir`): in the BFF seam use `root: true`.
- JSON in and out. Every answer, error included, is `Cache-Control: no-store`. Errors are the API's OperationOutcome (`issue[0].code`, `diagnostics`): a 404 for a record or network that is not the caller's, an unknown id, **and a role that may not use the route** (the same body, so nothing can be told apart); 400 for a bad body or field (unknown fields are refused: send nothing the table does not list; never a tenant, network claim or account); 409 for a lost race or a state that does not allow it (`Conflict`, `InvalidTransition`); 401 for no token, a bad token, or the platform operator (no data access).
- A POST needs `Content-Type: application/json` even with no body (send `{}` or an empty body with the header), as every POST of the API. There is no `Idempotency-Key`: each command is repeatable by its state, so a client retries a call that failed or timed out and gets the same result.
- The tenant is the token's. The `networks` claim is **not** used here (it only routes the read routes of `routes_network.py`); the registry is asked on every call.
- Handles are the registry's own ids (`membership_id`, grant `id`, listing `id`): opaque, never a tenant id. Organisations are named (`organisation_name`); no body holds a tenant id, an account reference, a person or an agreement's content.
- Path ids: a network id is `net-` and 2 to 27 of `a-z0-9-` (31 characters at most); a record id is `[A-Za-z0-9][A-Za-z0-9_-]{0,63}`. Anything else is refused before any use case.
- Times are ISO 8601 UTC with a `Z`.

## Who may use which (a role not listed is a 404; the operator is a 401)

`tenant-admin` runs its own organisation's side; `network-admin` (of the network's owner) runs the sharing of the network. `lead` may ask for and withdraw a listing.

| Method and path | Roles | Body | Answer |
|---|---|---|---|
| `GET /network-admin/networks` | tenant-admin, network-admin | | `{"networks": [{id, name, status, is_owner, membership_id, membership_status, agreement_reference, agreement_version, accepted_agreement_version, agreement_behind, system_name, pathway_name, time_zone}]}` the networks the organisation belongs to or is invited to (`membership_status` `invited` or `active`) |
| `GET /network-admin/network/{id}/members` | network-admin (owner) | | `{"members": [{membership_id, organisation_name, role, status, invited_at, joined_at, left_at, accepted_agreement_version, agreement_behind}]}` every row, closed ones (`left`, `removed`) included |
| `POST /network-admin/network/{id}/members` | network-admin | `{"tenant_id": "<organisation id>"}` | 201 `{"membership_id", "status": "invited"}`. An unknown or inactive organisation is a 404 with the same body; an organisation already in the network is a 409 |
| `POST /network-admin/network/{id}/members/{membership}/remove` | network-admin | | `{"status": "removed", "grants_lapsed", "listings_withdrawn"}` |
| `POST /network-admin/network/{id}/leave` | tenant-admin | | `{"status": "left", "grants_lapsed", "listings_withdrawn"}`. The owner cannot leave (404) |
| `POST /network-admin/memberships/{membership}/accept` | tenant-admin | `{"agreement_version": <int>}` the version the administrator read; it must be the network's current one (409 otherwise) | `{"status": "active"}`; a repeat is the same |
| `POST /network-admin/network/{id}/agreement` | network-admin | `{"reference": "<id in the owner's document system>", "version": <int>}` a version higher than the current one | `{"agreement_version"}`. Members then show `agreement_behind` until they accept |
| `GET /network-admin/network/{id}/projection` | network-admin | | `{"members": [{membership_id, organisation_name, kinds: [{kind, status (active\|ended), ended_at, end_reason (left\|grant-ended\|replaced\|null)}]}]}` states and dates, never a row |
| `GET /network-admin/grants` | tenant-admin | | `{"grants": [grant]}` the organisation's own, every network |
| `GET /network-admin/network/{id}/grants` | network-admin (owner) | | `{"grants": [grant]}` every grant of the network |
| `POST /network-admin/grants` | tenant-admin | `{"network_id", "scope": "capacity"\|"directory"\|"criteria", "effective_from"?: ISO, "effective_to"?: ISO}` | 201 `{"id", "status": "proposed"}`; start defaults to now and may not be earlier; 409 if the scope already has an open grant (revise it) |
| `POST /network-admin/grants/{id}/approve` | tenant-admin (the grantor side), network-admin (the owner side) | | `{"effective": bool}` true when this was the second approval. The same person cannot give both approvals (409) |
| `POST /network-admin/grants/{id}/decline` | tenant-admin, network-admin | | `{"status": "declined"}` before both approvals only |
| `POST /network-admin/grants/{id}/end` | tenant-admin (the grantor only) | | `{"status": "ended"}`; stops future sharing only; the owner cannot end a member's grant |
| `POST /network-admin/grants/{id}/revise` | tenant-admin (the grantor) | `{"effective_from"?, "effective_to"?}` | 201 `{"id", "status": "proposed"}` a new version that replaces the approved grant when it is approved and starts |
| `GET /network-admin/network/{id}/listings` | network-admin (owner) | | `{"listings": [listing]}` |
| `GET /network-admin/network/{id}/listings/mine` | tenant-admin, lead | | `{"listings": [listing]}` the organisation's own |
| `POST /network-admin/network/{id}/listings` | tenant-admin, lead | `{"service_id": "<the service's id in the organisation>"}` | 201 `{"id", "status": "pending"}` |
| `POST /network-admin/network/{id}/listings/{listing}/admit` | network-admin | | `{"status": "done"}` |
| `POST /network-admin/network/{id}/listings/{listing}/reinstate` | network-admin | | `{"status": "done"}` |
| `POST /network-admin/network/{id}/listings/{listing}/decline` | network-admin | `{"reason": "<code>"}` | `{"status": "done"}` |
| `POST /network-admin/network/{id}/listings/{listing}/suspend` | network-admin | `{"reason": "<code>"}` | `{"status": "done"}` |
| `POST /network-admin/network/{id}/listings/{listing}/withdraw` | tenant-admin, lead | | `{"status": "done"}` |

Listing reason codes: `outside-area`, `outside-pilot`, `duplicate-listing`, `data-quality`, `safety-concern`, `agreement-breach`, `other`.

### The shapes

- **grant**: `{id, network_id, network_name, organisation_name, scope, status, version, effective_from, effective_to, agreement_version, allowlist_version, grantor_approved_at, owner_approved_at, ended_at, end_reason (ended\|lapsed\|superseded\|null), supersedes_id, effective}`. `status` is one of `proposed`, `grantor-approved`, `owner-approved`, `approved`, `declined`, `ended`, `lapsed`, `superseded`. **`effective` is computed at the time of the read** (approved by both, in its window, not ended): the screen shows it and never infers it from `status`.
- **listing**: `{id, organisation_name, service_id, status (pending\|admitted\|declined\|suspended\|withdrawn), reason, requested_at, decided_at}`. `service_id` is the member's own id for the service: the owner sees the organisation and that reference (a listing carries no service name yet: known issue).

## What the screens must know

- The first approval reads `{"effective": false}`; only the second reads true. A grant whose start is in the future is `approved` and not `effective` until then.
- `agreement_behind` is true for an active member whose accepted version is below the network's: show "agreement version N available".
- A member that left or was removed stays in `members` with `left_at`; its grants read `lapsed` and its listings `withdrawn`. Nothing is deleted.
- The platform operator's token never reaches these routes (401). Creating a network, offboarding and purging a tenant are the operator's script (`scripts/tenant_lifecycle.py`), not routes (TEN-075).
- Wiring: `app.state.network_admin = NetworkAdminServices(...)` (a dataclass of the use cases); with none the routes answer 500. No process builds the app yet.
