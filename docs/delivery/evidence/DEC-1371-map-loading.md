# DEC-1371 The map's loading picture and the load path: evidence

Branch `map-loading-placeholder` (from `rename-overwatch`; not merged, not pushed).

## What was built
- `components/map/MapPlaceholder.tsx` + `mapPlaceholder.module.css`: the loading picture (land, grid, roads, pale pins, two bars, the words "Loading the map…", spoken label "Loading the map.").
- `components/map/MapLoadingBox.tsx`: the same, in the map's 3 to 2 box, for the read stage (Map and network map).
- `TileMap.tsx`: shows the placeholder until MapLibre's `load`; `preloadMap()` / `useMapPreload()` start the chunks, the worker and the tile header early.
- `MapScreen`, `NetworkMap`, `RadarScreen`: call `useMapPreload()`; Map and network map show `MapLoadingBox` while the options are read.

## Tests (written first, red before the component existed)
- `MapPlaceholder.test.tsx`: spoken label and `role="status"`, the visible word, land and pins, no `style=`, no throw with nothing to fit, `animation: none` under `prefers-reduced-motion` and no hard-coded colours in the CSS, `MapLoadingBox` has no land, `preloadMap` is a no-op without WebGL.
- `TileMap.test.tsx` (MapLibre and PMTiles mocked): placeholder present at once, still present when the map object exists, gone on `load`; an `error` before load calls `onFailed`.
- Results are in the last section of this note.

## Where the time goes (harness: Vite build of the real components, the real 2.64 GB tile file, headless Chromium)
Local, no latency, once the map is mounted: the MapLibre chunk 51 ms; the worker request starts 65 ms after the chunk ends and takes about 200 ms; the tile header read starts only after the worker starts; the tiles follow 210 ms later; the first glyph file 70 ms after that; `load` about 900 ms after the placeholder first shows. The tile route's own latency locally is 2 to 10 ms per range. The real blob's latency was not measurable (read-only, signed out).

With an emulated 80 ms round trip and 12 Mbit/s, the map mounted 1.5 s after page start (standing in for the options read), three runs each, from the placeholder first showing to the map ready:

| | run 1 | run 2 | run 3 |
|---|---|---|---|
| before (nothing preloaded) | 2.78 s | 2.72 s | 2.40 s |
| after (`preloadMap()` at page start) | 1.53 s | 1.32 s | 1.73 s |

So the preload takes about 1.1 s off the wait that the placeholder hides. The harness serves the unminified MapLibre build (1.36 MB); production's is smaller, so the absolute figures are pessimistic and the saving is smaller on a fast line.

- Hidden by the placeholder: the chain after the options arrive (chunk, worker, header, tiles, glyphs).
- Shortened now: the chunk, the worker and the header read start during the options read.
- Not shortened (DEC-1371 item 5): the tile route is `no-store`, so the header and root directory are read from the blob on every open; `/map/*` has no long cache; the 520 KB worker; the first glyph file still waits for the first tiles.
- The land-ring bundle is 30 KB (9 KB gzipped) in the page chunk: not a cause. The options read was not measured (it needs the signed-in app) and is not what the owner described.

## Look
`DEC-1371-shots/map-loading.png` (the placeholder, the same box as the map), `map-ready.png`, `radar-loading.png`. The words "Loading the map…" show top centre; the page below does not move when the map arrives.

## Not verified
The signed-in production app; the blob's real latency; behaviour under a real `prefers-reduced-motion` setting (the CSS is tested for the rule, not rendered with it); screen-reader output (the markup is `role="status"` with a spoken label).
