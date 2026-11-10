# DEC-1372 One Map view with a "Who covers this area" layer: evidence

Branch `map-loading-placeholder` (from `rename-overwatch`; not merged, not pushed). It also holds DEC-1371 (the loading picture), one commit earlier.

## What was built
- `OptionsMap`: the layer toggle (`aria-pressed`), per-area styles and hatched overlaps on the tile map and in the schematic, the patient area marker "Patient area · <outward code>" only when `patientArea` is known, captions from `captionOf`. `initialCoverage` starts the layer on.
- `CoveragePanel`: the Radar's key and "Covering <district>" list, shown with the layer.
- `ViewToggle`: no Radar tab. `/radar` redirects to `/map?layer=coverage`; the Map page passes the query to `MapScreen`.
- `lib/map/caption.ts`, `lib/map/areaStyle.ts`, `outwardCode`, `coverSummary(covering, located)`.
- `RadarMap` and `RadarScreen` removed; `TravelDetails` and `CompareScreen` captions no longer claim a patient marker.
- `docs/design/redesign/advisor-clinical-wall.md` updated; DEC-1372 records the supersession.

## Tests (written first)
- `lib/map/caption.test.ts`: the patient sentence only with a patient, areas and route only when drawn, hatching only with the layer, zoom or schematic.
- `lib/advisor/postcode.test.ts`: `outwardCode`.
- `components/advisor/OptionsMap.coverage.test.tsx`: toggle off by default and on, `initialCoverage`, outlined areas differ by line and colour, overlaps hatched (3) and none for areas apart, pins kept, no drive-time or traffic wording, summary when the location is unknown, axe; "Patient area · DT4" never the full postcode, nothing about a patient when the location is unknown, bare "Patient area" for a non-code.
- `app/(advisor)/.../radar/page.test.tsx`: the redirect, including an odd reference. `map/page.test.tsx`: the layer off by default and on for `?layer=coverage`. `compare/page.test.tsx`: the Compare and Ways pages' existing checks, moved out of the old radar test.
- Existing tests changed: `ViewToggle` (no Radar), `OptionsList` (link goes to the layer), `OptionsMap` (new label and caption, no drive-time sentence), `TravelDetails` (new caption), `UnplacedNote` (Map only), `RadarScreens` (Radar describe removed; the not-found, outside-area and no-fit states it covered for Radar are the Map's own and are tested there).
- Results: the final run is in the commit's report. Not run: Playwright (another session's dev server holds `frontend/`), the whole back-end suite (no back-end change).

## Look
`DEC-1372-shots/map-coverage-layer.png`: the Map with the layer on (harness: the real component, the real tile file): outlined areas, hatched overlaps, the caption naming only what is drawn, the key below. In the harness fixture the patient sits exactly under the hospital-at-home pin, so its label is hidden by the pins there; that is the fixture, but a patient and a pin at one spot will hide the label in real use too.

## Why `patientArea` was null on production
See DEC-1372 item 7: not established. The locator works for DT and BH districts with the shipped file and the production API has the setting; the likely cause is the district stored on that case. It needs that case's stored district to confirm.

## Not verified
The signed-in app; the layer on a phone width; the redirect in a running server (tested as the thrown redirect); the Playwright radar spec, which is out of date and listed in DEC-1372.
