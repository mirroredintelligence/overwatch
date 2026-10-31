# WB12 routes: the network administrator's sign-in, the BFF of the network administration and of the member's sharing (TEN-080, TEN-081)

For the bundles that follow. Back end: `backend/src/diucs/application/use_cases/{network_admin,member_sharing,exchange_token}.py`, `adapters/inbound/fhir_rest/routes_network_admin.py`. Front end: `frontend/app/api/bff/network-admin/**`, `frontend/app/api/bff/sharing/**`, `frontend/lib/networkAdmin/*`. Fixtures written by the back end's own converters: `frontend/test/fixtures/network-admin-shapes.ts` (`network-admin-shapes.gen.py`, run from `backend/`).

## How a network administrator signs in (DEC-1260)

Staff sign-in, `POST /auth/token` on the owner's host: the person's group in the owner's verified directory is mapped to `network-admin` (the operator makes the first mapping: `uv run python scripts/tenant_lifecycle.py --operator NAME network-admin-group OWNER-TENANT GROUP-GUID`; later ones are the owner's tenant administrator's, `PUT /tenant/role-mappings` with `role: network-admin`). The exchange issues the role only while the host's tenant owns an active network (the registry is asked); otherwise the one 403. The BFF's session then has role `network-admin` and the proxy lets it into `/network-admin/**` only.

## Back end: the one new route

| Method and path | Roles | Answer |
|---|---|---|
| `GET /network-admin/sharing` (at the app root) | tenant-admin | `{ allowlist: { version, scopes: { capacity: [field], directory: [field], criteria: [field] } }, networks: [{ id, name, membership_id, membership_status, joined_at, left_at, agreement_reference, agreement_version, accepted_agreement_version, agreement_behind, shared: [{ scope, status (active\|ended), ended_at, end_reason (left\|grant-ended\|replaced\|null) }] }] }`. `shared` is what the network holds of THIS organisation now (states and dates), for an active membership only. Any other role the API's one 404, the operator a 401. |

## BFF: the network administrator (`withBff`, role `network-admin`, all `private, no-store`)

`networkId` is the one key the guard lets through, on the routes marked N: once, a network id the server offered (`GET .../networks`). With none named and exactly one owned network, that one; several, a 400; not offered or not owned, the one 404.

| Route | N | Back end | Answer |
|---|---|---|---|
| `GET /api/bff/network-admin/networks` | | `GET /network-admin/networks` | `{ networks: [{ id, name }] }` the networks it owns and is active in |
| `GET /api/bff/network-admin` | N | `.../network/{id}/members`, `.../projection` | `{ network: { id, name, agreementReference, agreementVersion, members: [{ id, organisation, role (owner\|member), status (invited\|active\|left\|removed), invitedAt, joinedAt, leftAt, acceptedAgreementVersion, agreementBehind }], health: [{ id, organisation, kinds: [{ kind, status, endedAt, endReason }] }] } }` |
| `POST /api/bff/network-admin/members` `{ organisationCode }` | N | `POST .../members` `{ tenant_id }` | 201 `{ id, status: 'invited' }`; an unknown, ineligible or already invited code is the one 404 |
| `POST /api/bff/network-admin/members/[id]/remove` | N | `POST .../members/{id}/remove` | `{ status: 'removed', grantsLapsed, listingsWithdrawn }` |
| `POST /api/bff/network-admin/agreement` `{ reference, version }` | N | `POST .../agreement` | `{ agreementVersion }` |
| `GET /api/bff/network-admin/grants` | N | `.../network/{id}/grants` | `{ network: { id, name }, grants: [{ id, organisation, scope, status, version, effectiveFrom, effectiveTo, agreementVersion, allowlistVersion, grantorApprovedAt, ownerApprovedAt, endedAt, endReason, effective }] }` |
| `POST /api/bff/network-admin/grants/[id]/approve` | | `POST /network-admin/grants/{id}/approve` | `{ effective }` |
| `POST /api/bff/network-admin/grants/[id]/decline` | | `POST /network-admin/grants/{id}/decline` | `{ status: 'declined' }` |
| `GET /api/bff/network-admin/listings` | N | `.../network/{id}/listings` | `{ network, listings: [{ id, organisation, serviceRef, status, reason, requestedAt, decidedAt }] }` |
| `POST /api/bff/network-admin/listings/[id]/admit` and `/reinstate` | N | `POST .../listings/{id}/admit` and `/reinstate` | `{ status: 'done' }`; no body |
| `POST /api/bff/network-admin/listings/[id]/decline` and `/suspend` `{ reason }` | N | the same names | `{ status: 'done' }`; `reason` one of `outside-area outside-pilot duplicate-listing data-quality safety-concern agreement-breach other` |

## BFF: the member's administrator (`withBff`, role `tenant-admin`)

| Route | N | Back end | Answer |
|---|---|---|---|
| `GET /api/bff/sharing` | | `GET /network-admin/sharing`, `.../grants`, `.../networks` | `{ organisationCode, allowlist: { version, scopes }, networks: [{ id, name, isOwner, membershipStatus, joinedAt, leftAt, agreementReference, agreementVersion, acceptedAgreementVersion, agreementBehind, shared: [{ kind, status, endedAt, endReason }], grants: [GrantRow without networkId] }] }`. `organisationCode` is the session's own tenant id, for its own administrator (DEC-1264) |
| `POST /api/bff/sharing/grants` `{ kind }` | N | `POST /network-admin/grants` `{ network_id, scope }` | 201 `{ id, status: 'proposed' }`. The key is `kind`: the guard refuses a key that names a scope |
| `POST /api/bff/sharing/grants/[id]/approve` | | `.../grants/{id}/approve` | `{ effective }` |
| `POST /api/bff/sharing/grants/[id]/decline` | | `.../grants/{id}/decline` | `{ status: 'declined' }` |
| `POST /api/bff/sharing/grants/[id]/end` | | `.../grants/{id}/end` | `{ status: 'ended' }` |
| `POST /api/bff/sharing/leave` | N | `POST .../network/{id}/leave` | `{ status: 'left', grantsLapsed, listingsWithdrawn }`; never the owner's own network |
| `POST /api/bff/sharing/agreement` `{ agreementVersion }` | N | `POST .../memberships/{membership}/accept` `{ agreement_version }` | `{ status: 'active' }`; the membership is the one the server found waiting (an invitation or a newer version): the browser holds no handle |

Every write needs the CSRF token (`X-CSRF-Token`, the session's) and answers a 403 `csrf` without it. The back end has no idempotency key on these routes (DEC-967), so the BFF sends none; each command is repeatable by its state. Errors: a 403 or 404 from the back end on a route that takes an id is the one 404; a 409 is `That changed while you were working. Reload and try again.`; a body that is not what was expected is a 502; the back end down is a 503.
