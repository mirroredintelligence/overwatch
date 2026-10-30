# W17 and W43: the lead's network variants (back end reads)

Bundle W9B. The lead's "System now" network variant (W17), and the phones and moves network variants (W43), designed as the minimal read routes the pages need. Tests: `test_network_lead_views.py` (unit, 20 cases), `test_network_lead_routes.py` (integration, with the role matrix).

## Decisions

### DEC-981 The lead's network views are two reads over the board and the directory, for every role that sees a network; moves have no network variant (W17, W43, TEN-082, DEC-134 item 8, DEC-136 items 1, 5 and 9)
Status: accepted (build wave 9, bundle W9B; under DEC-133). Affects: `application/use_cases/network_lead_views.py` (new), `routes_network_views.py` (new), `app.py`.

1. **System now** is `GET /network/{id}/system-now`: the counts of the network board by status (every key present: the six statuses and `unavailable`, a paused listing shown by name only), the number of services and of organisations shown, the pressure and the network pressure alert (DEC-982). It is derived from the cached board after the same gate as the board (`NetworkBoardProjector.get_board`), so it can show nothing the board does not. The tenant's own "System now" has chase cards, ladder steps and pending requests; none of that exists in a network (DEC-136 item 1), so the variant is the counts and the pressure.
2. **Phones** is `GET /network/{id}/phones`: one row per service in the network, from the directory joined to the board by the row reference: organisation, service, category, presentation, status (null when the board has no row for it), the stale flag and the report time, and the service line the organisation shared (`contact_label`, `contact_phone`, each null when none: "Phone to confirm"). Phoning is the only action on a network row (DEC-134 item 8). It never holds a reporter's number, a cover, a role or a hash: none is in any projection. The tenant's own phones list (reporters' phones grouped by what they hold) has no network meaning and is not touched.
3. **Moves** (U38, moving a service from one reporter's phone to another's) have no network variant. A move changes a tenant's own reporter roles; another organisation's reporters and covers are not shared (DEC-132, DEC-136 item 5: no cross-tenant writes), so there is nothing for a lead to move or to read. The W43 page keeps its Move buttons on the tenant view and shows no move controls in the network variant. No `moves` route exists.
4. **Roles.** Both routes take the five roles that see a network (`NETWORK_VIEW_ROLES`: advisor, clinical, lead, owner, exec), as the board, directory and criteria. They read nothing the board and the directory do not already give those roles, so a narrower rule (lead only) would add a refusal and no protection. The wall, reporter, anonymous link, support, audit, administrator and operator roles are the one 404, as on the other network routes.
5. **Gate and refusals.** Each route first checks the network is in the token's `networks` claim, then the registry (`require_member`, on every request): a network outside the claim, a tenant that is not an active member, a member who left, an unknown network and a refused role are the same 404 with the same body. No body names a tenant, a grant, a network id (the page already holds it) or a member's own service id.

## Hazards

None new beyond H-654 (a pressure state read as an instruction) in `TEN-082.md`.

## Known issues

| id | what | where | trigger |
|----|------|-------|---------|
| W17 | The network "System now" has no list of services to chase: a network has no prompts or ladder | `network_lead_views.py` | none: a stated limit; the board lists the services |
| W43 | The phones list is read-only and shows the service line only; no row has a reporter's number or a move | `network_lead_views.py` | none: DEC-136 items 1 and 5 |
| W43 | The service line is empty for every row until the producer has a source of one (see TEN-082) | `project_network.py` | the profile gains a service contact |

## Contracts

- `GET /network/{id}/system-now`, `GET /network/{id}/phones` (see `W9B-routes.md`).
- `QuerySystemNow`, `QueryPhones`, `NetworkSystemNow`, `NetworkPressureAlert`, `NetworkPhones`, `NetworkPhone`, `STATUS_KEYS`, `UNAVAILABLE_KEY` in `application/use_cases/network_lead_views.py`.

## Tenant pending

None. No statement is added: both read through `NetworkBoardProjector` and `QueryNetworkDirectory`.
