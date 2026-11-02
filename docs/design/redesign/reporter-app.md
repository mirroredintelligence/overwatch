# Reporter app and capacity links: implementation brief

Surface: the people at provider services who report capacity and answer bookings, and practitioners on a visit round. Phone first (320px up), often on bad signal, mid-shift.

Design: canvas https://claude.ai/artifact/7Akh3E4fV6oETJXRydM3rs (boards B1..B11, D1, St; Main is the route index). Look and morph rules come from the first redesign canvas (https://claude.ai/artifact/Nb8Zzui3LuDhQbqe8vjdku) and `docs/design/design-system.md`. Copy comes from `docs/spec/ui-screens.md` (Reporter, Reporter2, ReporterFirst, EmailCapacity, Booking*, ReporterApp1/2, MultiService*, SuspendLeaver), word for word where it still fits.

Status: design only. Nothing is built or tested on a device.

## Rules this surface adds

1. The figure is fixed: same place and size on every step, never animated (no count-up, fade or slide). Only the controls around it open, close and spring.
2. One primary action per screen (56px or more). Decline, closed-to-referrals and withdraw are outlined or dark, never a red danger button.
3. Status is shape plus word: Confirmed (tick), Due now (clock), Paused (dashed outline), Closed (box with a cross), Over capacity (triangle).
4. Bad signal says what happened, keeps what was typed, and offers a second way (try again, text, phone the shift lead). No spinner without words.
5. No patient information: age band, need, wanted-within, and "Referral details follow in SystmOne".
6. Each service is confirmed separately on multi-service phones.
7. Reduced motion: every state appears at once. The motion tokens are already zero under `prefers-reduced-motion`.

## Shared pieces

New (in `frontend/components/reporter/parts/`):

- `LinkFrame`: public page, light top bar with the mark and a "No login needed" tag, centred column up to 480px.
- `AppFrame`: dark top bar, bottom `TabBar` (Update, Services, Settings, Help; hidden on PIN, verify, locked, lost-phone, practitioner).
- `FigureCard`: service, label, `ReplyByTag`, the 96px figure with tabular numerals and its unit, "Recorded at 08:15".
- `NumberStepper`: minus, number box, plus, "referrals, usual range 0 to 8". Controls 76px. An empty value shows a dashed box with an en dash; the disabled primary says "Choose a number to send".
- `ReplyByTag`: clock icon plus "Reply by 10:30", a static time, not a countdown.
- `StatusTag`: the five status words in one component.
- `StateBanner`: tones offline, error, warning, info, each with an icon, a bold lead and what was kept.
- `ReasonChips`: single-select group (`radiogroup`) for decline, withdraw and not-reached.

Reuse: `Button`, `Chip`, `Banner`, `Panel`, `StatusMark`, `PinPad`, `CodeInput`, `MobileNumberField`, `CoverUntil`, `PhoneScreen`, `OptionButton`, and `Loading`/`Skeleton` from `components/ui/Skeleton.tsx`.

## Per route

### Capacity links

- `/l/[token]` (B1, B2, B3, D1): states loading, still right, different number (stepper opens in place, the figure does not move), first report, out of range (confirm), closed to referrals (confirm, UI only), sending, closed (expired or used, with renew), unavailable, bad signal. Desktop opens the stepper from the start in two columns. Data: `GET/POST /api/bff/links/[token]` (`confirm`, `number` with optional `confirmOutOfRange`, `closed`) and `POST .../renew`. Keep the one-read-per-view rule (the CSRF cookie is set by the browser read). Focus moves to the new heading after each step, and sending and sent are in a polite live region.
- `/l/thanks` (B1): thank you, read-only figure, next due, Change it (only while the link is valid, otherwise the shift lead's number), See the live board. Data comes from the page address (`lib/links/thanks.ts`).

### Booking requests

- `/l/[token]/booking` and `/app/booking/[ref]` (B4): states loading, request, decline reasons (open under Decline), booked, closed (expired, declined, cancelled, withdrawn, not reached). Build one `BookingDecisionView` with a `LinkFrame` wrapper and an `AppFrame` wrapper. Confirm is the single primary. Data: link purpose `booking-request`; app `GET /api/bff/reporter/bookings/[ref]` and `POST .../respond`. `coordinationPhone` is already in the link view.
- `/l/[token]/booking/change` (B5): change options, withdraw reasons, withdrawn (phone the SPOA if the patient was told), not reached reasons, cancelled by the SPOA, closed words. Data: link answers `withdraw` and `not-reached` with a reason (`lib/links/browser.ts`); closed states in `lib/links/model.ts`. `tel:` link when `coordinationPhone` is present, otherwise "phone the number on the register".

### App (`app/(reporter)/app/...`)

- `/app`: redirect only. Keep the logic (no session to pin, one service to respond, several to update, none to services, executive to planning). The Update tab reuses it.
- `/app/pin` (B6): `PinScreen`; dots, wrong, locked; `POST identity/pin/verify`.
- `/app/respond/[serviceId]` (B6, B2): same states as the link page in `AppFrame`; `GET .../services/[id]/prompt`, `POST .../report`.
- `/app/respond/[serviceId]/thanks` (B6): figure, next due, Today list, Change it; `GET .../services/[id]/history`.
- `/app/update` (B6): `GroupedUpdate`; one primary "Both still right", per-service Still right or Change (the stepper opens inline), partial failure shown on its own line; `GET reporter/services`, `POST reporter/reports/batch`.
- `/app/services` (B7): cards Confirmed, Due now (own "Update" primary), Paused (dashed); empty state "You have no services yet"; `GET reporter/services`.
- `/app/services/[id]/added` (B7): Yes or No; `POST .../accept`.
- `/app/services/[id]/cover` (B7): cover mobile, Until (Tonight, This week, A date); `POST .../cover`, `lib/reporter/cover.ts`.
- `/app/settings` (B8): grouped rows; add a visible "Sign out of every phone" link; `GET reporter/settings`, `PUT .../channel`, `PUT .../cover`.
- `/app/verify` (B8): the 30-day check; after Send code the same screen morphs to the six-digit entry with a resend countdown; `identity/device-code` and `.../verify`.
- `/app/locked` (B8): "Text me a code" primary; `identity/device-code`, `reporter/channel`.
- `/app/lost-phone` (B9): number, code, then "Waiting for a call-back"; `identity/new-phone`, `.../verify`, `identity/sign-out-everywhere`.
- `/app/sign-out-all` (B9): confirm with a dark primary; `identity/sign-out-everywhere`, `reporter/settings`.
- `/app/notifications-off` (B9): three steps; new one-line nudge banner on respond and update while notifications are off; `identity/channel`, `reporter/channel`, client permission check.

### Practitioner

- `/app/practitioner` (B10): greeting, optional status chips, offers, today, two actions; `GET practitioner/shift`, `PUT .../settings`.
- `/app/practitioner/round` (B10): Next, Later, and a collapsed "Done today (n)"; state tags Accepted, Offered, Done.
- `/app/practitioner/location` (B10): two radios plus the three promises; `PUT practitioner/settings`.
- `/app/practitioner/offers/[id]` (B11): facts, live expiry countdown with tabular numerals, Accept primary, Decline outlined, address only after accept; `GET practitioner/visits/[id]`, `.../accept`, `.../decline`.
- `/app/practitioner/visits/[id]` (B11): address, maps, status radios; the "About how long?" chips (10 to 60) open only on "On my way"; closed states in words; `POST .../status`. The phone position is never read or sent.

## Bad signal and offline

Today only `/offline` is precached; nothing queues or persists an unsent figure. Design: keep the number on screen, say "No signal. Not sent yet.", offer Try again now (same idempotency key) and Send it by text instead. The number lives in component memory only (the address holds a bearer token, which must never be stored). No background sync for links: a link is one-use, and a stale replay could overwrite a newer figure. `/offline` cannot name the coordination number (DEC-660 item 3): keep that on every offline surface.

## Gaps and flags

1. `LinkView` has no capacity text line field, so the text fallback cannot be built until the back end adds one. Ship the rest first.
2. Check a confirmed out-of-range report reaches the lead's "Reports to check" before the page says the lead will be told.
3. The closed-to-referrals confirm is UI only.
4. The practitioner location text points to a Settings route that does not exist: add a small page or change the sentence.
5. The notifications-off nudge needs only the client permission check.
6. The Update tab must reuse the `/app` redirect logic.

## Build order

0. Foundations (frames, tab bar, `FigureCard`, `NumberStepper`, `ReplyByTag`, `StatusTag`, `StateBanner`, `ReasonChips`; adopt `Loading` and `Skeleton`), with tests and axe.
1. Capacity link loop (B1, B2, B3, D1). Depends on 0. Existing BFF only.
2. Booking pages (B4, B5). Depends on 0.
3. App frame, PIN, respond, thanks, grouped update (B6). Depends on 0 and 1.
4. Services, added, cover (B7). Depends on 3.
5. Settings and recovery (B8, B9). Depends on `AppFrame`; the nudge depends on 3.
6. Practitioner (B10, B11). Depends only on 0; can run alongside 3 to 5.
7. Offline text fallback, after the back end adds the text line.

Each step ends with updated component tests, axe clean, the matching e2e path re-run, and the old component removed in the same change.

## Open design questions

1. Should the Update tab show a badge when a service is due? (Not drawn: a live figure on a fixed element.)
2. Should Decline need a second confirm? (Drawn without: the reason chips are the pause.)
3. Is "Send it by text instead" wanted, given gap 1?
4. Should the practitioner's status and location live on one Settings page or the two existing screens?
