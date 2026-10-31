# WB2: routes and shapes for the bundles that follow

WB2 adds no route. It changes what two existing ones send, and adds one topic. A front-end bundle needs only the first section.

## `GET /events` (the live stream, root path, roles wall, advisor, clinical, lead, exec)

Server-sent events, each `event: <name>\ndata: <json>\n\n`:

| event | data | when |
|---|---|---|
| `board` | `{"serviceId": "<fhir id>", "kind"?: "capacity" or "status" or "booking", "changedAt": "<UTC instant, Z>"}` | a service's board entry changed (unchanged) |
| `board-whole` (new) | `{"changedAt": "<UTC instant, Z>"}` | a change that belongs to no one service: the pressure banner moved, or an approved criteria set; refetch the whole board |
| `heartbeat` (new) | `{"changedAt": "<UTC instant, Z>"}` | every 15 s when nothing else was sent; it replaces the bare `: keep-alive` comment on this stream |

The page treats 45 s without any of these as a dead stream (`HEARTBEAT_SILENCE_MS` in `lib/board/liveness.ts`). The BFF relay (`/api/bff/events`) forwards `board`, `board.updated`, `booking.updated`, `board-whole` and `heartbeat`; the last two carry the time only. `GET /network/{id}/events` is unchanged: it still sends `: keep-alive` comments and `network-board`.

## `POST /admin/report-flags/{flag_id}/$resolve` (lead; mounted as `app.py` says)

The route path, the body and the response are unchanged. A `phoned` outcome now records its figure through RecordAdvisorPhoned: the audit entry of the new report holds `told` (`not-accepting` for 0, else `accepting`) and `flagId`. The flag list description of a `differs-from-phoned` flag raised by a phoned figure reads "`<service>`: the advisor phoned `<n>` at `<hh:mm>`, but the last `<text|app|link|email>` said `<n>` at `<hh:mm>`." (London times); the reverse direction keeps its earlier wording.

## Service Bus

New topic `codes.dispatch` (one-hour time to live, no duplicate detection), subscription `code-sender`, read by `code_sender.py`. Payload of a `SendCode` message: `sealed_code`, `sealed_phone`, `recipient_key`, `purpose`, `issued_at`; `DiscardCode` carries the same and is never opened.

## Channels

A tenant's email channel recorded from now on has provider `twilio`, a `fromAddress`, an optional display name, and no `secretRef` (a `secretRef` on a Twilio email channel is refused). It sends with the tenant's text-line Account SID and token. A channel recorded earlier with provider `smtp` still works.
