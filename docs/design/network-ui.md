# Network screens: specification for the UI

Status: specification, prepared for the network front-end tasks. Not externally certified.
Sources: `docs/delivery/tenancy-audit/D-frontend-ui.md` (sections 2e, 2g, 3.3, 3.4, 5.2, 5.4, 6, 8.2, 9), `docs/spec/ui-screens.md`, `docs/design/design-system.md`, DEC-014, DEC-019, DEC-122, DEC-129, DEC-132, DEC-134, DEC-136.
Product name: Community Overwatch. The file name is `network-ui.md`; the ledger row named `network-views.md` (see section 13).

This document fixes the words, the screens and the element ids that the network front-end tasks build from. Where a builder would otherwise invent a word, a screen or an id, this document decides it. It builds nothing: no component, route, style or mock is in it. The live design canvas is not edited (DEC-129, DEC-133 item 4); section 14 records what the snapshot lacks.

## 1. Rules that bind every screen

- Same layout and same components as the tenant view. The only differences on a network view are the scope header (section 3), an organisation label on every row, the removal of everything private to a tenant (pending counts, booking state, reporter contact, case data, comment lines, next-due times, audit), and no write action. Source: DEC-136 item 1, audit D section 2e.
- The network view is a list of facts. It never sorts or colours organisations as better or worse, shows no score or rank, and says `Not ranked` where order could be read as rank. Order is category, then organisation name, then service name. Source: design-system section 13.
- Network rows have no Request booking, I phoned, They declined, clinical escalation or alert subscription. The only action on a network row is to read the service line number and phone the service. Source: DEC-134 item 8, DEC-136 items 1, 5 and 9, audit D question Q11.
- The browser holds and sends no tenant, network or scope identifier. A viewer chooses between two fixed route families: the tenant's own routes and `/network/...`. The back end binds the scope from the route and the verified token. A service in the network is identified in the page by an opaque `data-service-ref`, an organisation by an opaque `data-org-ref`, and a row by `data-row-ref`. The source tenant id never reaches the browser and is never rendered. Source: DEC-134 item 3, DEC-136 item 11, audit D section 3.3.
- Not a member, or any refusal, reads as `Network view not available` (section 5), never as "forbidden" or "not found" in a way that reveals whether the network exists. Source: DEC-134, audit D risk 6.
- Figures come from each organisation's own reports and age from the report time. A stale figure is shown as `Not updated` or `Last known` with the time of the last figure. The network board never shows an old figure as current. Source: DEC-134 item 6 (figures are recomputed at read time, so staleness shows as Not updated).
- Network rows carry no comment line (the free-text comment is not shared), no next-due time, no pending chip and no reporter information. Source: DEC-136 item 1, audit D question Q9.
- The scope header never disappears, including in the Last known and unavailable states. Source: audit D R16, plan section 7.
- The network view and the wall board never fall back silently. A change of scope, a stopped share or a lost stream is always said on the screen (sections 5 and 6). Source: audit D R3, plan section 7 default.
- Every interactive element has a stable `data-el` id from section 10. An id never embeds a service id, an organisation id, a row number, a date or any other dynamic value (audit D risk 8, O05).

## 2. Vocabulary and fixed wording

The strings below are exact. `{Name}`, `{n}`, `{m}`, `{age}`, `{duration}`, `{time}`, `{date}` and `{Organisation name}` are placeholders filled from configuration or data, never constants. Copy never names a place, an organisation or a telephone number: names come from configuration. The product name is Community Overwatch.

| Key | Wording | Where it is used |
|---|---|---|
| scope label, own | `Showing: Our organisation` | Scope header on the tenant's own routes and on the wall (section 3) |
| scope label, network | `Showing: Network, {Network name}` | Scope header on the network routes and on a network wall (section 3) |
| own-row marker | `Your organisation` | Marker on the viewer's own organisation rows in the network view (section 3) |
| switch, own | `Our organisation` | First link of the scope switch (section 3) |
| switch, network | `Network` | Second link of the scope switch (section 3) |
| network board heading | `{Network name} capacity` | Page title and heading of the network board (section 4) |
| read-only banner title | `Read only` | Title of the read-only note on network views (section 3) |
| read-only banner body | `You cannot book or change these services from here. Phone the service to check.` | Body of the read-only note (section 3) |
| count line | `{n} services from {m} organisations`; for one of each `1 service from 1 organisation` | Above the rows of the network board and the directory (section 4) |
| shared-by label on a detail | `Shared by {Organisation name}` | Service detail, first section (section 4) |
| footer | `No patient information on this screen` and `Figures are reported by each organisation. Sorted by category, then organisation. Not ranked.` | Footer of the network board (section 4) |
| unit when unknown | `Phone to confirm` | Unit of a figure that cannot be read (section 4) |
| age line, current | `Updated {age} ago` | Under a tile or a row whose figure is current (section 4) |
| age line, not updated | `Not updated for {duration} · was due {time}` | Under a tile or a row whose figure is late (section 4) |
| listing paused | `Not available on the network. Phone to confirm.` | Tile of a paused listing, shown with the existing Not updated badge, a `?`, the unit `Phone to confirm`; no new status word (section 4) |
| service line label | `Service line`; with none shared, `No number shared` | Label of the service line number (section 4) |
| directory source | `Entered by the organisation`; later `From the Directory of Services` | Source line in the service detail (section 4) |
| empty network | title `No services are shared yet`; body `When organisations share their capacity with {Network name}, their services appear here.` | Empty network board and directory (section 4) |
| empty filter | title `No services match this filter`; body `Clear the filter to see all organisations.` | Empty filtered list (section 4) |
| all chip | `All organisations` | First organisation chip (section 4) |

The status words are the seven existing ones of the status badge: `Accepting`, `Limited`, `Not accepting`, `Over capacity`, `Not updated`, `Out of hours`, `Last known`. No tone, status word or token is added.

## 3. Scope header and organisation label

The scope header is part of the board component, not page chrome, so it appears on a wall that has no URL bar (audit D R16).

Wireframe, tenant board with the network available:

```
Showing: Our organisation          [Our organisation] [Network]
```

Wireframe, network board:

```
Showing: Network, {Network name}   [Our organisation] [Network]
```

### ScopeHeader

- `ScopeHeader` is a labelled landmark: `role="region"`, accessible name `Which board you are viewing`. It reads `Showing: Our organisation` or `Showing: Network, {Network name}` and holds the `ScopeSwitch`.
- `ScopeSwitch` is a `nav` of two links, not a toggle: `Our organisation` and `Network`. The current one is marked with `aria-current="page"`. The switch is absent for a viewer whose organisation is in no network, and on screens where the viewer has no network; then only the own-scope label shows.
- On a wall screen there is no switch, only the label, in the display type token.

Artboard: ScopeHeader

One line: the permanent header of every board and network route.

```
[label] Showing: Our organisation (el: SCOPE-HEADER-LABEL)
[link] Our organisation (el: SCOPE-SWITCH-OWN-LINK)
[link] Network (el: SCOPE-SWITCH-NETWORK-LINK)
```

Behaviour:

- A change of scope is a navigation to the other route family. It is never a parameter, never a request carrying an identifier.
- The header appears on: the board and its network variant, the advisor home counts and options, the map, the shift lead `System now`, the exec home and service detail, the network services pages, and the wall board. It never appears on screens that have no network variant: registration, criteria editing, the reporter app, link pages, clinical screens, help, the support console.
- The header never disappears, including in the Last known and unavailable states.

### Organisation label and own-row marker

Every network row shows the organisation display name under the service name, in the caption type token (`--type-caption-size`). Rows of the viewer's own organisation in the network view also carry the marker `Your organisation`: a text label with the `--c-tint` background, `--c-ink` text and a `--c-primary` border (existing tokens only). It never uses a status colour and is never the only way to tell the rows apart: the marker is a word.

Artboard: OrgLabel and own-row marker

```
[row] UCR West (el: NET-BOARD-ROW)
Organisation: {Organisation name}. Your organisation (the marker text, on the viewer's own rows).
```

### Read-only note and banner tones

The read-only note is a `Banner` with tone `info`, the title and body of section 2. It is shown once above the list on the network board, the options and the detail views, never on every row. The rows themselves have no buttons except the service line link.

```
[banner info] Read only. You cannot book or change these services from here. Phone the service to check. (el: SCOPE-READONLY-NOTE)
```

Scope banner tones use the existing tones only: `info` for read-only and for "no longer shown" notes; `warning` for a fall-back or a stopped share; `offline` for network not available and last known. Banner tones: `info`, `warning`, `offline`. No tone is added, so no DEC-122 addendum is needed.

```
[banner warning] Updates from {Organisation name} are delayed. Its services show Not updated. (el: SCOPE-BANNER-NOTICE)
```

### Wall variant

The header on a wall reads `Showing: Network, {Network name}` or `Showing: Our organisation`, visible from across the room. It never disappears, including in the Last known and unavailable states.

Hand-off: TEN-069 builds `ScopeHeader`, `ScopeSwitch`, `OrgLabel`, the own-row marker and the read-only note from this section.

## 4. N3: Network capacity board and directory

### N3: Network board, directory and history

Artboards below are for the network routes `/network/board`, `/network/services`, `/network/services/[id]`, `/network/history` and `/network/week`. The role set of `/network/board` is the tenant board's.

### Artboard: NetworkBoard

Route `/network/board`. Purpose: the live capacity of every organisation's services that the network shares, read only.

```
Showing: Network, {Network name}   [Our organisation] [Network]
{Network name} capacity
{n} services from {m} organisations
[chip] All organisations (el: NET-BOARD-ORG-ALL-CHIP)
[chip] {Organisation name} (el: NET-BOARD-ORG-CHIP)
[btn] Tiles (el: NET-BOARD-VIEW-GRID-BTN)
[btn] List (el: NET-BOARD-VIEW-LIST-BTN)
[banner info] Read only. You cannot book or change these services from here. Phone the service to check. (el: SCOPE-READONLY-NOTE)
[tile] UCR West, Your organisation (el: NET-BOARD-TILE)
Urgent community response. Status: Accepting. Figure: 4, unit beds, shown large.
Used 2 of 6. Updated 4 minutes ago.
[link] {Service line number} (el: NET-BOARD-PHONE-LINK)
[link] See history (el: NET-BOARD-HISTORY-LINK)
Sorted by category, then organisation. Not ranked.
No patient information on this screen
```

Behaviour:

- The organisation chips filter in place. There is no navigation and no request carries an organisation id: the filter is client-side over the rows the back end returned. `All organisations` first, then the viewer's own organisation, then the others alphabetically; each chip carries `aria-pressed`.
- The view toggle `Tiles` and `List` switches the layout only; the same entries and the same order.
- A tile shows: the service name; the organisation line, with the own-row marker where it applies; the category label as the wall board gives it (`Urgent community response`, `Same day emergency care`, `Inpatient beds`, `Virtual beds`, `Care packages`, and the labels of the remaining categories as `ui-screens.md` and the W05 prompt give them); the status badge; the big number and its unit; a `Used {x} of {y}` bar; the age line.
- Status styles, number sizes and states are the wall board's (accepting, limited, not accepting, over capacity, not updated, out of hours), unchanged. The listing-paused tile uses the Not updated styling and the wording of section 2.
- No comment line, no `pending` chip, no next-due time.
- The board updates live from the network stream. Losing the stream shows the section 5 Last known state.
- Focus order follows reading order. The board is virtualised past a few hundred rows (design-system section 11).

### Artboard: NetworkBoardList

The same entries as `NetworkBoard`, as rows at phone width, same fields, same order.

```
[row] UCR West (el: NET-BOARD-ROW)
Organisation name · Your organisation
Urgent community response · Accepting · 4 · Used 2 of 6
Updated 4 minutes ago
```

### Artboard: NetworkServices

Route `/network/services` (built by TEN-071). A list of the directory with an organisation filter and a category filter.

```
Showing: Network, {Network name}   [Our organisation] [Network]
{n} services from {m} organisations
[chip] All organisations (el: NET-SERVICES-ORG-CHIP)
[chip] Urgent community response (el: NET-SERVICES-CATEGORY-CHIP)
[row] UCR West (el: NET-SERVICES-ROW)
Organisation name · Urgent community response · DT4
Opening hours summary · Service line {Service line number}
```

Each row shows: the service name; the organisation; the category; the postcode district (for example `DT4`); the opening hours summary; the service line.

### Artboard: NetworkServiceDetail

Route `/network/services/[id]`, where `[id]` is the opaque `row_ref`. Sections: `About this service`, `Opening hours`, `Service line`, `Criteria`.

```
About this service
UCR West
Shared by {Organisation name}
Urgent community response · {Location name} · DT4
Entered by the organisation
Opening hours
Service line
Service line {Service line number}
[link] Service line {Service line number} (el: NET-BOARD-PHONE-LINK)
[section] Criteria (el: NET-SERVICE-CRITERIA-SECTION)
Accepts: {Needs accepted}
Does not accept: {Needs excluded}
Ages: {Age range}
Districts: {Postcode districts}
Review by {date}
[dialog] Criteria (el: ADV-CRIT-DIALOG)
```

The criteria section is read only and shows the current version only: `Accepts`, `Does not accept`, `Ages`, `Districts`, `Review by {date}`. There is no change reason, no owner and no history (audit D question Q10). The criteria dialog variant has no `Report a problem with these criteria` button, because that message would go to a tenant the viewer cannot message.

If no number is shared, the service line row reads `No number shared` and has no link.

### Artboard: NetworkHistory

Route `/network/history` (TEN-070 adds the page). A read-only list of what departed members shared. Each row is labelled `Left the network on {date}` or `Stopped sharing on {date}`, under a `warning` banner.

```
[banner warning] This is history. These services are not on the live board. (el: SCOPE-BANNER-NOTICE)
[row] UCR West (el: NET-BOARD-ROW)
Organisation name · Left the network on {date}
```

`NetworkHistory` is never reachable from the live board's tiles. It is reached only from the notice in section 5 and from the link `See history` (`NET-BOARD-HISTORY-LINK`).

### Artboard: NetworkWeek

Route `/network/week` (TEN-082). A short entry that states what the screen contains: only capacity-derived measures appear (on-time updates, status counts, pressure over time). Small groups are hidden.

```
Not shown: fewer than 10.
No per-member breakdown is shown.
```

The full screen belongs to TEN-082. This entry names the rule, nothing more (DEC-136 item 14; audit D question Q13).

## 5. N5: Unavailable and degraded states

Every state below has one artboard, its wording, its behaviour and who sees it. Every refusal reads the same: one wording for all, so a viewer cannot tell from it whether the network exists.

### N5: Unavailable and degraded states

### Artboard: NetworkNotAvailable

Who sees it: a viewer who is not a member, whose role may not see the network, who asks for an unknown network, or whose request is refused for any other reason.

```
[panel] Network view not available (el: NET-STATE-PANEL)
Ask your administrator.
[link] Back to our organisation (el: NET-STATE-BACK-LINK)
```

Link target: the viewer's own board.

### Artboard: NetworkPaused

Who sees it: a viewer when the network is paused (the owner has paused the network view).

```
[panel] The network view is paused (el: NET-STATE-PANEL)
{Network name} is not sharing capacity at the moment. Phone services to check.
[btn] Try again (el: NET-STATE-RETRY-BTN)
```

### Artboard: NetworkMembershipEnded

Who sees it: the members of an organisation that has left the network, on the network routes.

```
[panel] Your organisation has left {Network name} (el: NET-STATE-PANEL)
You can see the history of what was shared until {date}.
[link] See history (el: NET-BOARD-HISTORY-LINK)
```

The live figures are removed from the page. Only the history is reachable.

### Artboard: NetworkSourceStopped

Who sees it: every viewer of the network board, as a strip above the live board. Tone `info`.

```
[banner info] No longer shown: {Organisation name}. It stopped sharing on {date}. (el: SCOPE-BANNER-NOTICE)
[link] See history (el: NET-BOARD-HISTORY-LINK)
```

Several organisations are joined with commas. The strip stays until the viewer leaves the page.

### Artboard: NetworkSourceDelayed

Who sees it: every viewer, per organisation, above that organisation's rows. Tone `warning`.

```
[banner warning] Updates from {Organisation name} are delayed. Its services show Not updated. (el: SCOPE-BANNER-NOTICE)
```

### Artboard: NetworkOffline

Who sees it: every viewer when the network stream or the board call fails. Tone `offline`.

```
[banner offline] Network board offline since {time} (el: NET-STATE-PANEL)
Figures are the last known and may be wrong. Use the whiteboard and phone process.
[btn] Try again (el: NET-STATE-RETRY-BTN)
```

The figures stay on screen as Last known with the time of the last figure. The tiles use the Last known badge. The header still says `Showing: Network, {Network name}`.

### Artboard: NetworkWallFallback

Who sees it: a wall set to the network board, when the wall loses that board: the membership ended, the network paused, or the grant mechanics refused. Tone `warning`.

```
[banner warning] No longer showing {Network name}. Showing: Our organisation. (el: SCOPE-BANNER-NOTICE)
Showing: Our organisation
```

The wall falls back to its organisation's board. It never shows a blank or a stale network board, and it never falls back silently. The banner stays until the administrator changes the screen's board.

### Behaviour for each state

- Last known is kept per scope. When a screen's board is changed, the old scope's figures are dropped, never shown as Last known of the new scope.
- A 401 or a "screen revoked" answer clears the board and returns the screen to pairing (audit D R1, R2).
- Whether the live region announces the state: `NetworkNotAvailable`, `NetworkPaused`, `NetworkMembershipEnded`, `NetworkSourceStopped`, `NetworkSourceDelayed`, `NetworkOffline` and `NetworkWallFallback` are announced politely, once.
- Whether the state removes figures: `NetworkNotAvailable`, `NetworkPaused` and `NetworkMembershipEnded` remove all network figures from the page. `NetworkOffline` keeps them as Last known. `NetworkSourceDelayed` keeps them as Not updated.
- Whether the state blocks navigation: none of them does.

## 6. N4: Wall screens

Route `/lead/screens` for the tenant administrator (TEN-072 builds it; the lead role area is where the pairing page lives, W08).

### N4: Wall screens

### Artboard: ScreenList

Heading `Wall screens`. A table with the columns `Screen`, `Where it is`, `Status`, `Last seen` and `Shows`.

```
Wall screens
[table] Screen, Where it is, Status, Last seen, Shows (el: SCREENS-LIST-TABLE)
Status values: Online, updated {time} · Offline since {time} · Waiting to be connected
Shows values: Our organisation · Network, {Network name}
[btn] Change board (el: SCREENS-BOARD-BTN)
[btn] Unpair (el: SCREENS-UNPAIR-BTN)
[btn] Re-pair (el: SCREENS-REPAIR-BTN)
[btn] Add a wall screen (el: SCREENS-ADD-BTN)
```

Status values are `Online, updated {time}`, `Offline since {time}` and `Waiting to be connected`. `Shows` values are `Our organisation` and `Network, {Network name}`. `Add a wall screen` leads to the existing pairing form (ScreenPairing, W08).

### Artboard: ScreenBoardChoice

A dialog, focus trapped and returned.

```
Which board does {Screen name} show?
[radio] Our organisation (el: SCREENS-BOARD-OWN-RADIO)
[radio] Network, {Network name} (el: SCREENS-BOARD-NETWORK-RADIO)
Your organisation is not in a network.
[btn] Save (el: SCREENS-BOARD-SAVE-BTN)
[btn] Cancel (el: SCREENS-BOARD-CANCEL-BTN)
The screen changes the next time it refreshes. Its header always says which board it shows.
```

When the organisation is in no network, only the first option is shown, with the hint `Your organisation is not in a network.`

### Artboard: ScreenClaim

The confirm step added to pairing (audit D R14). The existing pairing wording is unchanged.

```
Check before you connect
You are connecting a screen to {Organisation name}. It will show our organisation's capacity only. It never shows patient information.
First seen {time} · {device class}
[btn] Connect screen (el: SCREENS-CLAIM-CONFIRM-BTN)
[btn] Cancel (el: SCREENS-CLAIM-CANCEL-BTN)
```

The existing pairing wording (`Code shown on the screen`, `Screen name`, `Where it is`, `Connect screen`, `Cancel`, `Screen connected`) is unchanged.

### Artboard: ScreenUnpair

A dialog.

```
Unpair {Screen name}?
The screen stops showing the board and returns to its pairing code. You can pair it again at any time.
[btn] Unpair screen (el: SCREENS-UNPAIR-CONFIRM-BTN)
[btn] Cancel (el: SCREENS-CLAIM-CANCEL-BTN)
```

### Artboard: WallNetwork

The wall board in network mode: the wall board of the `Main` artboard, with the header `Showing: Network, {Network name}`. Tiles are as in section 4, without the footer line about sorting. The `WALL-TILE` id is kept, and the organisation line sits under each service name.

```
Showing: Network, {Network name}
[tile] UCR West (el: WALL-TILE)
Organisation name
[status] Accepting
4 beds
Updated 4 minutes ago
```

### Artboard: ScreenDisconnected

```
This screen is not connected.
Ask your lead to connect it.
Code shown on the screen: {pairing code}
```

The code is shown as the pairing screen shows it.

### Behaviour

- Changing the board needs the tenant administrator role and the existing `If-Match` concurrency of TEN-067.
- The choice list is built by the back end from the organisation's active memberships. An administrator cannot pick a network the organisation is not in. The page never sends a network id the server did not offer.
- Unpairing and re-pairing change the screen's state, never the other screens'.

## 7. N1: Network administration

Routes `/network-admin` (members and agreement), `/network-admin/grants` and `/network-admin/listings`, for the network administrator of the owner organisation. The owner reads no member's private data (DEC-132 item 2), and the pages say so in one line:

`You see who has joined, what each organisation agreed to share and whether it is arriving. You never see another organisation's private data.`

### N1: Network administration

### Artboard: NetworkMembers

A table with the columns `Organisation`, `Status` (`Invited`, `Active`, `Left`, `Removed`), `Joined`, `Left`, `Agreement version accepted`. Where a member is behind the current agreement, the cell carries the flag `Agreement version {n} is available`.

```
Network members
You see who has joined, what each organisation agreed to share and whether it is arriving. You never see another organisation's private data.
[table] Organisation, Status, Joined, Left, Agreement version accepted (el: NADM-MEMBERS-TABLE)
[btn] Add an organisation (el: NADM-MEMBER-ADD-BTN)
[btn] End membership (el: NADM-MEMBER-END-BTN)
Nothing here yet.
```

### Artboard: NetworkMemberAdd

The field `Organisation code` with the help `The code is on the organisation's administration page.` An unknown, ineligible or already invited code all answer with the same message, so no list of other tenants is shown.

```
Add an organisation
[input Organisation code] (el: NADM-MEMBER-CODE-INPUT)
The code is on the organisation's administration page.
[btn] Send invitation (el: NADM-MEMBER-SEND-BTN)
[btn] Cancel (el: SCREENS-BOARD-CANCEL-BTN)
We could not add that organisation. Check the code with them.
```

### Artboard: NetworkMemberEnd

A dialog. A second administrator's confirmation is asked, as the audit F rule requires.

```
End membership for {Organisation name}?
Its sharing stops now. What it already shared stays in the history, marked with today's date.
A second administrator must confirm this.
[btn] End membership (el: NADM-MEMBER-END-CONFIRM-BTN)
[btn] Cancel (el: SCREENS-BOARD-CANCEL-BTN)
```

### Artboard: NetworkAgreement

```
Agreement
[input Agreement reference] (el: NADM-AGREEMENT-REFERENCE-INPUT)
[input Version] (el: NADM-AGREEMENT-VERSION-INPUT)
Only the reference and version are stored, never the agreement itself.
[btn] Record agreement (el: NADM-AGREEMENT-RECORD-BTN)
```

### Artboard: NetworkGrants

A table with the columns `Organisation`, `Scope` (`Capacity`, `Directory`, `Criteria`), `Purpose` (`Network capacity view`), `From`, `To`, `Approval` (`Waiting for the organisation`, `Waiting for the network owner`, `Approved`, `Ended`, `Lapsed`, `Declined`) and `Version`. Buttons `Approve` and `Decline` appear on grants that wait for the owner.

```
Grants
[table] Organisation, Scope, Purpose, From, To, Approval, Version (el: NADM-GRANTS-TABLE)
Waiting for the network owner
[btn] Approve (el: NADM-GRANT-APPROVE-BTN)
[btn] Decline (el: NADM-GRANT-DECLINE-BTN)
Nothing here yet.
```

### Artboard: NetworkListings

A table with the columns `Organisation`, `Service`, `Status` (`Waiting`, `Admitted`, `Paused`, `Declined`, `Withdrawn`). The buttons `Admit`, `Decline`, `Pause` and `Reinstate` appear by status. The reason select for `Decline` and `Pause` offers the codes below; a reason is a code, never free text.

```
Listings
[table] Organisation, Service, Status (el: NADM-LISTINGS-TABLE)
[btn] Admit (el: NADM-LISTING-ADMIT-BTN)
[btn] Decline (el: NADM-LISTING-DECLINE-BTN)
[btn] Pause (el: NADM-LISTING-PAUSE-BTN)
[btn] Reinstate (el: NADM-LISTING-REINSTATE-BTN)
[select Reason] (el: NADM-LISTING-REASON-SELECT)
Options: Outside the area, Outside the pilot, Duplicate listing, Data quality, Safety concern, Agreement, Other
Nothing here yet.
```

### Artboard: NetworkHealth

Per organisation: `Last update received {time}`, `Delay {duration}`, `Updates refused {n}`.

```
Health
[table] Organisation, Last update received, Delay, Updates refused (el: NADM-HEALTH-TABLE)
Last update received {time} · Delay {duration} · Updates refused {n}
Nothing here yet.
```

### Artboard: NetworkAdminHistory

A read-only history of membership and grant decisions, with dates. Reached from the link `History`.

```
[link] History (el: NADM-HISTORY-LINK)
Read-only history of membership and grant decisions, with their dates.
Nothing here yet.
```

Every table has the empty state `Nothing here yet.`

## 8. N2: Sharing with the network

Route `/admin/sharing`, for the member organisation's administrator (TEN-081). Sharing is read only. Other organisations see only the fields listed in this section.

### N2: Sharing with the network

### Artboard: SharingOverview

Heading `Sharing with the network`. Intro: `Sharing is read only. Other organisations see only the fields listed here. No patient information is ever shared.` One card per scope, `Capacity`, `Directory` and `Criteria`, each with its state, the field list and its buttons.

```
Sharing with the network
Sharing is read only. Other organisations see only the fields listed here. No patient information is ever shared.
[card] Capacity: Sharing since {date} (el: SHARE-SCOPE-CARD)
[list] Fields: the labels of the field table below (el: SHARE-FIELDS-LIST)
[btn] Approve (el: SHARE-APPROVE-BTN)
[btn] Decline (el: SHARE-DECLINE-BTN)
[btn] End sharing (el: SHARE-END-BTN)
[btn] Propose sharing (el: SHARE-PROPOSE-BTN)
[btn] Leave network (el: SHARE-LEAVE-BTN)
[link] History (el: SHARE-HISTORY-LINK)
```

The state of each scope is one of: `Sharing since {date}`, `Waiting for your approval`, `Waiting for the network owner`, `Not sharing`, `Ended on {date}`.

### Artboard: SharingFields

The list rendered from the allowlist the API returns, not typed here (see the field table below). `AllowlistFields` (TEN-081) renders the labels.

```
[list] Field labels from the allowlist (el: SHARE-FIELDS-LIST)
Never shared: reporters' names, phone numbers, devices and PINs; links and codes; messages sent or received; bookings and cases; audit entries; anything about a patient.
```

### Artboard: SharingEnd

A dialog.

```
End sharing {scope}?
New data stops being shared straight away. What was already shared stays in the network history, marked with today's date.
[btn] End sharing (el: SHARE-END-CONFIRM-BTN)
[btn] Cancel (el: SCREENS-BOARD-CANCEL-BTN)
```

### Artboard: SharingLeave

A dialog.

```
Leave {Network name}?
All your sharing ends now. What was already shared stays in the history, marked with the date you left.
[btn] Leave network (el: SHARE-LEAVE-CONFIRM-BTN)
[btn] Cancel (el: SCREENS-BOARD-CANCEL-BTN)
```

### Artboard: SharingAgreement

```
Agreement version {n} is available.
[btn] Accept version {n} (el: SHARE-AGREEMENT-ACCEPT-BTN)
```

The reference is shown; the content never is.

### Artboard: SharingHistory

Who the data has been shared with, since when, and what ended.

```
[link] History (el: SHARE-HISTORY-LINK)
Shared with {Network name} since {date}
Ended on {date}
```

### Field labels

The component `AllowlistFields` (TEN-081) renders the labels below from the allowlist the API returns, keyed by the DTO field name of `domain/rules/projection.py` (TEN-052). This table carries the labels. TEN-081's test fails when a field in the allowlist has no label, or a label has no field. Internal references are not listed on the screen.

| Scope | DTO field | Label on the screen |
|---|---|---|
| Directory | `service_name` | Service name |
| Directory | `category` | Service category |
| Directory | `active` | Whether the service is active |
| Directory | `source` | Where the entry came from |
| Directory | `contact_label`, `contact_phone` | Service line name and number |
| Directory | `location_name`, `city` | Location name and town or city |
| Directory | `postal_district` | Postcode district only (for example DT4) |
| Directory | `latitude`, `longitude` | Map position of the location |
| Directory | `opening_hours` | Opening hours |
| Directory | `source_service_id`, `source_version` | not listed (internal reference) |
| Capacity | `measure`, `unit_label` | What the figure counts and its unit |
| Capacity | `established_capacity` | Established capacity |
| Capacity | `can_exceed_established` | Whether the service can go over established capacity |
| Capacity | `limited_level_percent` | Level at which the service shows as Limited |
| Capacity | `cadence` | How often the service reports |
| Capacity | `suspended` | Whether the service is suspended |
| Capacity | `value`, `reported_at` | The latest reported figure and when it was reported |
| Capacity | `confirmed_since` | How many bookings were confirmed since that report (a count, never the bookings) |
| Capacity | `reply_window_minutes`, `stale_warning_hours` | How long a reply is expected, and when the figure counts as old |
| Capacity | `source_service_id`, `source_version`, `report_id`, `valid_until` | not listed (internal reference) |
| Criteria | `age_min`, `age_max` | Age range |
| Criteria | `districts` | Postcode districts |
| Criteria | `accepts`, `excludes` | Needs accepted and needs excluded |
| Criteria | `review_by` | Review-by date |
| Criteria | `version` | Current version number |
| Criteria | `source_criteria_id`, `source_service_id` | not listed (internal reference) |

## 9. Variants of existing screens

One row per existing screen group from audit D section 2e. Each row says whether a network variant exists, what changes, what is removed, the route, the task that builds it and the element ids it reuses.

| Screen group | Network variant | What changes | What is removed | Route | Built by | Element ids reused |
|---|---|---|---|---|---|---|
| Wall board | Yes | Header reads Showing: Network, {Network name}; organisation line under each name | Footer sorting line | Wall screen, board mode | TEN-070, W05 to W07 | WALL-TILE |
| TileStates | Yes | Tiles use the network rows and the Last known badge | Pending chip | Board | W06 | WALL-TILE |
| BoardDown | Yes | Falls back to the own board with the banner of section 5 | Blank network board | Wall screen | TEN-072, W07 | none |
| BoardSurge | Yes | Over-capacity tiles show their organisation line | Next-due times | Board | W10 | none |
| BoardQuiet | Yes | Empty network state of section 2 | Comment lines | Board | W10 | none |
| Advisor home counts | Yes | Counts over the network rows, with the scope header | Pending counts | Advisor home | W13 | none |
| Options and not-suitable list | Yes | Read-only rows labelled by organisation, sorted as the tenant list, `Sorted by travel time. Not ranked.` | Request booking, I phoned, They declined, clinical escalation per row | Advisor options | W14 | none |
| Bookings | No network variant | None | None | Advisor bookings | none | none |
| Map | Yes | Network rows with map pin, same toggles | Booking actions | Advisor map | W17 | ADV-MAP-TOGGLE-LIST, ADV-MAP-TOGGLE-MAP |
| Shift lead System now | Yes | Network rows, scope header | Pending and next-due | Shift lead | W40 | none |
| Exec home | Yes | Network counts, scope header | Exec alerts for other organisations | Exec home | W50 | none |
| Exec service detail | Yes | Network service detail of section 4 | Alert subscription | Exec service detail | W50 | none |
| Exec alerts | Own organisation only | Alerts stay on the own organisation | Any network alert | Exec alerts | W50 | EXEC-ALERT |
| Week summary | Yes | Capacity-derived measures only (section 4) | Per-member breakdown | Week | TEN-082 | none |
| Criteria dialog | Yes | Read only, current version (section 4) | Report a problem with these criteria | Criteria dialog | W14 | ADV-CRIT-DIALOG |

No network variant exists for: bookings, TileStates pending, planning, registration, criteria editing, the reporter app, link pages, clinical screens, help, the tour, learn, and the support console.

The options-list variant shows read-only rows for other organisations' services that meet the case's criteria, labelled by organisation, sorted as the tenant list, with `Sorted by travel time. Not ranked.` It has no `Request booking`, no `I phoned` and no `They declined`, no clinical escalation per row, and only the service line number. The advisor records a call in their own case, with the organisation name, the service name and the as-of time copied as typed text at the time (DEC-134 item 8). The case screens are the tenant's and are not changed here.

Exec alerts show the own organisation only (DEC-136 item 9).

## 10. Element ids

Every id is upper case with hyphens, in the form `<AREA>-<SCREEN>-<THING>`, two to five segments, at most 48 characters, with no placeholder or data value in it. Repeated elements share one id and carry their identity in a data attribute: `data-service-ref`, `data-org-ref` or `data-row-ref`. Areas: `SCOPE` (header, switch, banners), `NET` (network board, services, states), `NADM` (network administration), `SHARE` (sharing), `SCREENS` (wall screen administration).

**New ids**

| Id | Element | Screen | Built by |
|---|---|---|---|
| `SCOPE-HEADER-LABEL` | Scope label text | ScopeHeader | TEN-069 |
| `SCOPE-SWITCH-OWN-LINK` | Switch link to the own organisation | ScopeSwitch | TEN-069 |
| `SCOPE-SWITCH-NETWORK-LINK` | Switch link to the network | ScopeSwitch | TEN-069 |
| `SCOPE-READONLY-NOTE` | Read-only banner | Board, options, detail | TEN-069 |
| `SCOPE-BANNER-NOTICE` | Scope banners: stopped sharing, delayed, fall-back | Board, wall | TEN-070, TEN-072 |
| `NET-BOARD-TILE` | Network tile (carries `data-service-ref`) | NetworkBoard | TEN-070 |
| `NET-BOARD-ROW` | Network list row (carries `data-service-ref`) | NetworkBoardList, NetworkHistory | TEN-070 |
| `NET-BOARD-ORG-ALL-CHIP` | All organisations chip | NetworkBoard | TEN-070 |
| `NET-BOARD-ORG-CHIP` | Organisation chip (carries `data-org-ref`) | NetworkBoard | TEN-070 |
| `NET-BOARD-VIEW-GRID-BTN` | Tiles view toggle | NetworkBoard | TEN-070 |
| `NET-BOARD-VIEW-LIST-BTN` | List view toggle | NetworkBoard | TEN-070 |
| `NET-BOARD-PHONE-LINK` | Service line link | NetworkBoard, detail | TEN-070, TEN-071 |
| `NET-BOARD-HISTORY-LINK` | See history link | NetworkBoard, states | TEN-070 |
| `NET-SERVICES-ROW` | Directory row (carries `data-service-ref`) | NetworkServices | TEN-071 |
| `NET-SERVICES-ORG-CHIP` | Organisation filter chip on the directory (carries `data-org-ref`) | NetworkServices | TEN-071 |
| `NET-SERVICES-CATEGORY-CHIP` | Category filter chip | NetworkServices | TEN-071 |
| `NET-SERVICE-CRITERIA-SECTION` | Read-only criteria section | NetworkServiceDetail | TEN-071 |
| `NET-STATE-PANEL` | Unavailable panel | NetworkNotAvailable and the other states | TEN-070 |
| `NET-STATE-BACK-LINK` | Back to our organisation link | NetworkNotAvailable | TEN-070 |
| `NET-STATE-RETRY-BTN` | Try again button | NetworkPaused, NetworkOffline | TEN-070 |
| `NADM-MEMBERS-TABLE` | Members table | NetworkMembers | TEN-080 |
| `NADM-MEMBER-ADD-BTN` | Add an organisation button | NetworkMembers | TEN-080 |
| `NADM-MEMBER-CODE-INPUT` | Organisation code field | NetworkMemberAdd | TEN-080 |
| `NADM-MEMBER-SEND-BTN` | Send invitation button | NetworkMemberAdd | TEN-080 |
| `NADM-MEMBER-END-BTN` | End membership button | NetworkMembers | TEN-080 |
| `NADM-MEMBER-END-CONFIRM-BTN` | End membership confirmation | NetworkMemberEnd | TEN-080 |
| `NADM-AGREEMENT-REFERENCE-INPUT` | Agreement reference field | NetworkAgreement | TEN-080 |
| `NADM-AGREEMENT-VERSION-INPUT` | Agreement version field | NetworkAgreement | TEN-080 |
| `NADM-AGREEMENT-RECORD-BTN` | Record agreement button | NetworkAgreement | TEN-080 |
| `NADM-GRANTS-TABLE` | Grants table | NetworkGrants | TEN-080 |
| `NADM-GRANT-APPROVE-BTN` | Approve grant button | NetworkGrants | TEN-080 |
| `NADM-GRANT-DECLINE-BTN` | Decline grant button | NetworkGrants | TEN-080 |
| `NADM-LISTINGS-TABLE` | Listings table | NetworkListings | TEN-080 |
| `NADM-LISTING-ADMIT-BTN` | Admit button | NetworkListings | TEN-080 |
| `NADM-LISTING-DECLINE-BTN` | Decline listing button | NetworkListings | TEN-080 |
| `NADM-LISTING-PAUSE-BTN` | Pause button | NetworkListings | TEN-080 |
| `NADM-LISTING-REINSTATE-BTN` | Reinstate button | NetworkListings | TEN-080 |
| `NADM-LISTING-REASON-SELECT` | Reason select | NetworkListings | TEN-080 |
| `NADM-HEALTH-TABLE` | Health table | NetworkHealth | TEN-080 |
| `NADM-GRANT-DECLINE-CONFIRM-BTN` | Decline grant confirmation | NetworkGrants dialog | TEN-080 |
| `NADM-LISTING-CONFIRM-BTN` | Decline or pause listing confirmation (with the reason select) | NetworkListings dialog | TEN-080 |
| `NADM-HISTORY-LINK` | History link | NetworkAdminHistory | TEN-080 |
| `SHARE-SCOPE-CARD` | Scope card (Capacity, Directory, Criteria) | SharingOverview | TEN-081 |
| `SHARE-FIELDS-LIST` | Field list rendered from the allowlist | SharingFields | TEN-081 |
| `SHARE-APPROVE-BTN` | Approve button | SharingOverview | TEN-081 |
| `SHARE-DECLINE-BTN` | Decline button | SharingOverview | TEN-081 |
| `SHARE-DECLINE-CONFIRM-BTN` | Decline confirmation | SharingOverview dialog | TEN-081 |
| `SHARE-PROPOSE-BTN` | Propose sharing button | SharingOverview | TEN-081 |
| `SHARE-END-BTN` | End sharing button | SharingOverview | TEN-081 |
| `SHARE-END-CONFIRM-BTN` | End sharing confirmation | SharingEnd | TEN-081 |
| `SHARE-LEAVE-BTN` | Leave network button | SharingOverview | TEN-081 |
| `SHARE-LEAVE-CONFIRM-BTN` | Leave network confirmation | SharingLeave | TEN-081 |
| `SHARE-AGREEMENT-ACCEPT-BTN` | Accept agreement version button | SharingAgreement | TEN-081 |
| `SHARE-HISTORY-LINK` | History link | SharingOverview, SharingHistory | TEN-081 |
| `SCREENS-LIST-TABLE` | Wall screens table | ScreenList | TEN-072 |
| `SCREENS-ADD-BTN` | Add a wall screen button | ScreenList | TEN-072 |
| `SCREENS-BOARD-BTN` | Change board button | ScreenList | TEN-072 |
| `SCREENS-BOARD-OWN-RADIO` | Our organisation option | ScreenBoardChoice | TEN-072 |
| `SCREENS-BOARD-NETWORK-RADIO` | Network option | ScreenBoardChoice | TEN-072 |
| `SCREENS-BOARD-SAVE-BTN` | Save board button | ScreenBoardChoice | TEN-072 |
| `SCREENS-BOARD-CANCEL-BTN` | Cancel board button | ScreenBoardChoice | TEN-072 |
| `SCREENS-UNPAIR-BTN` | Unpair button | ScreenList | TEN-072 |
| `SCREENS-UNPAIR-CONFIRM-BTN` | Unpair confirmation | ScreenUnpair | TEN-072 |
| `SCREENS-REPAIR-BTN` | Re-pair button | ScreenList | TEN-072 |
| `SCREENS-CLAIM-CONFIRM-BTN` | Connect screen button on the confirm step | ScreenClaim | TEN-072 |
| `SCREENS-CLAIM-CANCEL-BTN` | Cancel button on the confirm step | ScreenClaim | TEN-072 |

**Reused ids**

Ids that already exist in the prompts or specs and keep their meaning in the network variants. The telemetry event carries `view.scope` and `network.id`, so no `NET-` copy of these is invented (section 11).

| Id | Element | Screen | Built by |
|---|---|---|---|
| `WALL-TILE` | Wall tile, in network mode too | WallNetwork | W05, TEN-072 |
| `ADV-CRIT-DIALOG` | Criteria dialog, read only in the network variant | NetworkServiceDetail | W14 |
| `ADV-MAP-TOGGLE-LIST` | Map and list toggle, list side | Map variant | W17 |
| `ADV-MAP-TOGGLE-MAP` | Map and list toggle, map side | Map variant | W17 |
| `EXEC-ALERT` | Exec alert, own organisation only | Exec alerts | W50 |

## 11. Telemetry

- The attributes the front-end tasks add (audit D section 6): `view.scope` with the value `tenant` or `network`; `network.id`, opaque, carried only on events from the network routes.
- `ui.sse` carries the scope.
- Route templates, the only route names in telemetry: `/network/board`, `/network/services`, `/network/services/[id]`, `/network/history`, `/network/week`, `/network-admin`, `/admin/sharing`, `/lead/screens`.
- No organisation name, tenant id or source tenant id appears in any attribute.
- Element ids follow the O05 pattern `^[A-Z0-9]+(-[A-Z0-9]+)*$`.

## 12. Accessibility and motion

- `ScopeHeader` is a labelled landmark (`role="region"`, accessible name `Which board you are viewing`). The switch is a `nav` of two links.
- A change of scope is a navigation, announced by the page title: `{Network name} capacity` or `{Area name} capacity`.
- The own-row marker and the organisation line are text. Status is a word, a shape and a colour, never colour alone.
- Filters are `aria-pressed` chips.
- Dialogs trap focus and return it to the control that opened them.
- Live regions announce data changes once, politely.
- The layout works at 200 percent zoom and at 320 px width.
- No new motion. Existing tokens and the DEC-019 values stand (sheet 280 ms, captions 16 px). Reduced motion keeps opacity and drops movement. No decorative animation on any figure.

## 13. Build hand-offs and decisions

Each hand-off names the task, the sections it builds from, and the files it owns. The plan (`docs/delivery/tenancy-plan.md`) names no file paths, so the names below are the component and route names this document uses.

| Task | Builds from | Owns (components and routes) |
|---|---|---|
| TEN-067 | Section 6 (the wall board setting and the fallback flag in the API; no UI) | Back-end setting for the wall board scope |
| TEN-068 | Sections 1 and 5 (the route families, the refusal rule, the availability check) | BFF routes for `/network/...`, availability check, stream relay |
| TEN-069 | Sections 3 and 12 | `ScopeHeader`, `ScopeSwitch`, `OrgLabel`, the own-row marker, the read-only note |
| TEN-070 | Sections 4 and 5, including the history page | `/network/board`, `/network/history`, `NetworkUnavailable`, the Last known rule per scope |
| TEN-071 | Section 4 (directory) | `/network/services`, `/network/services/[id]` |
| TEN-072 | Section 6 | `/lead/screens`, `ScreenList`, `ScreenBoardChoice`, `ScreenClaim`, `ScreenUnpair`, `WallNetwork` |
| TEN-080 | Section 7 | `/network-admin`, `/network-admin/grants`, `/network-admin/listings` |
| TEN-081 | Section 8, with `AllowlistFields` keyed by the TEN-052 allowlist | `/admin/sharing`, `SharingOverview`, `SharingFields`, `AllowlistFields` |
| TEN-082 | Section 4 (`NetworkWeek`) and the rule of section 11 | `/network/week` |
| W05 to W50 amendments | Section 9 (the network variant of each existing screen) | The existing screen files, with the variant as specified |

Decisions this document takes, each with its source:

1. No `Unavailable` status word is added. A paused listing uses the Not updated badge and the wording of section 2 (DEC-122, design-system section 13).
2. A wall falls back to its organisation's board, with a banner, rather than going blank (audit D R3, plan section 7 default).
3. One wording for every refusal: `Network view not available` (DEC-134, audit D risk 6).
4. Inviting a member uses an `Organisation code`, so no list of other tenants is shown (DEC-136 item 3).
5. The pairing confirm step (`ScreenClaim`) is added to the existing pairing flow (audit D R14, question Q16).
6. No per-member breakdown in any owner view (DEC-136 item 14).
7. No comment line on network rows (DEC-136 item 1, audit D question Q9).
8. The figure on a network row is the reported figure net of confirmed bookings only (DEC-134 item 6, audit D question Q9).
9. Criteria content is shown, current version only, read only (audit D question Q10).
10. Phoning is the only action on a network row (DEC-136 item 9, audit D question Q11).
11. Alerts on the exec screens are for the own organisation only (DEC-136 item 9, audit D question Q12).
12. The week measures are capacity-derived only (DEC-136 item 14, audit D question Q13).
13. History is shown only, marked with the leave date (DEC-132 item 6, audit D question Q17).
14. The file is named `network-ui.md`, where the ledger row named `network-views.md` (see the evidence of TEN-063).

## 14. Canvas differences

The repository snapshot of the design canvas lacks what this document adds. The snapshot is not edited here (DEC-129). The differences, for the v1.1 pass:

- All network screens: the network board, its list and tiles, the directory, the service detail, the history, the week entry, and the states of section 5.
- The scope header and the scope switch, and the organisation label with the own-row marker.
- The wall screen administration (sections 6) and the pairing confirm step (`ScreenClaim`).
- The network administration (section 7) and the sharing screens (section 8).
- The network variants of existing screens (section 9).

The snapshot's existing tokens, components and status words are used as they are; no new token, colour, status word, Banner tone or motion is introduced by this document.

## 15. As built: TEN-080 and TEN-081 (where the screens differ from sections 7 and 8, and why)

Each point is a decision of the build (DEC-1260 to DEC-1266 in `docs/delivery/fragments/TEN-080.md` and `TEN-081.md`).

- Sign-in. The network administrator is the owner organisation's own role: a group of the owner's directory is mapped to `network-admin`, and the token exchange gives the role only while the host's organisation owns an active network (the registry is asked, never the token).
- `/network-admin/history` is a fourth page (the `History` link of N1 and the `NetworkAdminHistory` artboard). `/admin/sharing` keeps its history on the same page (`#history`), as a section.
- `NetworkMemberEnd`: the line `A second administrator must confirm this.` is not shown. The back end ends a membership in one step (TEN-077), so the line would be untrue. A membership that is invited or active can be ended; the owner's own row and closed rows cannot.
- `NetworkHealth`: the columns are `Organisation`, `Capacity`, `Directory`, `Criteria`, each `Sharing`, `Not sharing` or `Ended on {date}`. The registry holds no last-update time, delay or refusal count, so `Last update received`, `Delay` and `Updates refused` are not shown (nothing is invented).
- `NetworkListings`: a listing has no service name yet, so `Service` is the organisation's own reference for the service. There is a `Reason` column. `Decline` and `Pause` open a dialog with the reason select (`Choose a reason` first) and a confirmation; a reason is one of the seven codes.
- `NetworkGrants`: a grant nobody has approved reads `Waiting for the organisation and the network owner`; one the owner approved first reads `Waiting for the organisation`; an approved grant whose window has not started reads `Approved, starts on {date}`; a replaced one reads `Replaced by a newer version`. There is no criteria endorsement per version (DEC-136 item 4: the owner's approval of the grant covers the scope).
- `NetworkMemberAdd`: the `Organisation code` is the organisation's own id, shown only to its own administrator on `/admin/sharing` (`Your organisation code`). An unknown, ineligible and already invited code give the one message.
- `SharingOverview`: one more state, `Approved. Sharing starts on {date}`, for an approved grant whose window has not started (`Sharing since` would be untrue). A newer version waiting for approval shows over the one in force, which is still said. The field list is rendered from the back end's allowlist through the table of section 8; a field with no sentence stops the list and the page says so.
- The browser's key for the kind is `kind`, not `scope`: the input guard refuses every key that names a scope.
