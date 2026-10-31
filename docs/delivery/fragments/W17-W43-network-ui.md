# W17, W43 and TEN-082: the network variants of the lead's pages, and the network week (front end)

Bundle WB10. The back end is W9B's (`W17-W43-network.md`, `TEN-082.md`); nothing was rebuilt. Tests: `components/network/{NetworkSystemNowView,NetworkPhonesView,NetworkWeekView}.test.tsx`, `components/exec/NetworkWeek.test.tsx`, `lib/network/week.test.ts`, `app/(network)/network/pages.test.tsx`, `test/guards/network-views.test.tsx`.

## Decisions

### DEC-1199 The network's System now is the counts and the pressure state (W17; DEC-981, DEC-982)
Status: accepted (bundle WB10). `/network/system-now` shows the network board's counts by status (every one of the seven keys, the paused ones as "Not available on the network"), "{n} services from {m} organisations", "As at {time}", and the pressure as a STATE: a warning notice "Network pressure is high" ("{n} services are limited, not accepting or over capacity. High from {m}.") while the alert is raised, an info notice "Network pressure is rising" at the watch level, none while normal. No instruction is worded (H-654); no organisation or service is named; no chase, ladder or request exists in a network. It reads every minute and keeps the last good counts, marked, when a read fails (never zeros). The own lead page (`LeadOverview`) gains the `Showing: Our organisation` header with the switch to this page.

### DEC-1200 The network's phones are a read-only table with phoning as the only action (W43; DEC-981 item 2, DEC-136 items 1, 5)
Status: accepted. `/network/phones`: one row per service (service, organisation with the own marker, category, status, last report in London time, service line). The line is a link to phone or "Phone to confirm"; a paused listing says "Not available on the network". The page says that reporters' phones, covers and moves are the organisation's own and are not shared; there is no move control. `PhonesList` (the organisation's own) gains the own header and the switch.

### DEC-1201 The network week is capacity-derived figures, hidden when small, withheld when few, and history not status (TEN-082; DEC-983, DEC-136 item 14)
Status: accepted. `NetworkWeek` (`components/exec/NetworkWeek.tsx`) shows the hours sampled, the capacity updates on time, the share of each status, the hours at each pressure and, in a disclosure, the pressure of each sampled hour (London time). A hidden measure reads "Not shown: fewer than 10."; a withheld week reads "This week is not shown. Too few organisations shared capacity for it to be shown without identifying one." with no figure and no series; every state says "No per-member breakdown is shown." and "This is what the network board showed, hour by hour. It is not a live status." `NetworkWeekView` reads the last complete week by its Monday (computed in the browser from its clock, as the tenant's week does), with Earlier week / Later week (never past the last complete one) and Try again; a role that does not read the week (the back end's 404 or the BFF's 403) gets the "not available" panel; the page itself sends such a role to /forbidden. The executive's own week page gains the header and the switch.

## Hazards

| id | hazard | control | verified by | status |
|----|--------|---------|-------------|--------|
| H-847 | The week's small figures let a reader work out one member's own performance (H-653 at the page) | the page shows what the back end sends and nothing it hides; hidden measures say so and carry no value (the parser refuses a hidden value or a shown figure with none); no per-member view exists | `NetworkWeek.test.tsx`, `parse.test.ts` | closed for the front end |
| H-848 | A pressure state or a week is read as a live status or an instruction (H-654 at the page) | the wording is a statement of counts and a history; no verb to the reader | `NetworkSystemNowView.test.tsx`, `NetworkWeek.test.tsx` | closed for the front end |

## Known issues

| id | what | where | trigger |
|----|------|-------|---------|
| W17 | The network System now has no list of services to chase (a network has no prompts) | `NetworkSystemNowView` | none: a stated limit |
| W43 | The service line is empty for every row until the producer has a source of one (W9B): the page says "Phone to confirm" | back end `project_network.py` | the profile gains a service contact |
| TEN-082 | The week page computes "the last complete week" from the browser's clock | `NetworkWeekView` | a back end default for `weekStart` |
| TEN-082 | A quiet network is not sampled, so a week can show gaps (the page shows the hours sampled) | back end | the hourly sampler (W9B known issue) |

## Contracts

`NetworkSystemNowView`, `NetworkPhonesView`, `NetworkWeekView`, `NetworkWeek`, `lib/network/week.ts` (`isMonday`, `lastCompleteWeekStart`, `addWeeks`, `addDays`, `weekStartQuery`); pages `/network/system-now`, `/network/phones`, `/network/week`.
