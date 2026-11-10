# DEC-1366 Advisor v2: visual comparison with the SPoA design

Our pages (sample data, Playwright at 1280x800 and 390x844) are in
`C:/Users/smith/AppData/Local/Claude-Data/claude_pzs8sxrjxfjjc/side-session-notes/local_6b6d8548-9366-46cd-bb24-60e2d8116987/v2-shots/`.
The design's are in
`C:/Users/smith/AppData/Local/Claude-Data/claude_pzs8sxrjxfjjc/side-session-notes/local_9d2a7d81-e53c-4143-aa68-34aa40b4d997/design-shots/`.

| View | Ours | Design |
|---|---|---|
| Capacity, 1280 | `v2-capacity-1280.png` | `spoa-desktop-1-overview.png` |
| Capacity, 390 | `v2-capacity-390.png` | `spoa-mobile-1-overview.png` |
| Finder, 1280 | `v2-finder-1280.png` | `spoa-desktop-4-finder.png` |
| Finder with choices, 1280 | `v2-finder-choice-1280.png` | `spoa-desktop-5-finder-choice.png` |
| Finder, 390 | `v2-finder-390.png` | `spoa-mobile-4-finder.png` |
| Finder with choices, 390 | `v2-finder-choice-390.png` | `spoa-mobile-5-finder-choice.png` |
| Finder, a group open | `v2-finder-group-1280.png`, `v2-finder-group-390.png` | (none) |

The shots were taken from a throwaway page with stubbed data (not committed). The real pages inside the staff shell
were not looked at signed in.

Known differences from the design: the app shell supplies the header (brand and the switch row differ); locations are
postcode districts, not named areas ("East Dorset" is not held); the rings use the product's status colours from
`tokens.css`; our text is 14px and up (the design uses 12px); status is a dot or shape with its word, never colour alone.
