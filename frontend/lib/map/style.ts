import type { StyleSpecification, LayerSpecification } from 'maplibre-gl';

// The map's look (DEC-1362): OS Open Zoomstack vector tiles from our own origin, drawn in the app's quiet
// palette so the pins and areas on top stay the loudest thing. Layer names are the Zoomstack layers. Glyphs
// (place names) are served from /map/fonts, so nothing leaves the origin.

export const TILES_PATH = '/api/bff/map/tiles';
export const ATTRIBUTION = 'Contains OS data © Crown copyright and database right 2026';

const ROAD_MAJOR = ['Motorway', 'A Road', 'B Road'];
const SETTLEMENTS = ['Capital', 'City', 'Town', 'Village', 'Suburban Area', 'Hamlet', 'Other Settlement'];

const width = (...stops: [number, number][]) => ['interpolate', ['exponential', 1.6], ['zoom'], ...stops.flat()] as never;

export function mapStyle(origin: string): StyleSpecification {
  const layers: LayerSpecification[] = [
    { id: 'land', type: 'background', paint: { 'background-color': '#F4F6F5' } },
    { id: 'sea', type: 'fill', source: 'os', 'source-layer': 'sea', paint: { 'fill-color': '#D3E7F2' } },
    { id: 'foreshore', type: 'fill', source: 'os', 'source-layer': 'foreshore', paint: { 'fill-color': '#EAE7D6' } },
    { id: 'urban', type: 'fill', source: 'os', 'source-layer': 'urban_areas', paint: { 'fill-color': '#E9ECEB' } },
    { id: 'green', type: 'fill', source: 'os', 'source-layer': 'greenspaces', paint: { 'fill-color': '#E1EDDD' } },
    { id: 'wood', type: 'fill', source: 'os', 'source-layer': 'woodland', paint: { 'fill-color': '#D5E6D0' } },
    { id: 'water', type: 'fill', source: 'os', 'source-layer': 'surfacewater', paint: { 'fill-color': '#C2DDEC' } },
    { id: 'rivers', type: 'line', source: 'os', 'source-layer': 'waterlines', paint: { 'line-color': '#A9CCE0', 'line-width': width([8, 0.4], [14, 1.6]) } },
    { id: 'buildings', type: 'fill', source: 'os', 'source-layer': 'buildings', minzoom: 13, paint: { 'fill-color': '#D9DEDF' } },
    {
      id: 'roads-minor',
      type: 'line',
      source: 'os',
      'source-layer': 'roads',
      minzoom: 10,
      filter: ['!', ['in', ['get', 'type'], ['literal', ROAD_MAJOR]]],
      layout: { 'line-cap': 'round', 'line-join': 'round' },
      paint: { 'line-color': '#FFFFFF', 'line-width': width([10, 0.4], [14, 3]) },
    },
    {
      id: 'roads-major',
      type: 'line',
      source: 'os',
      'source-layer': 'roads',
      filter: ['in', ['get', 'type'], ['literal', ROAD_MAJOR]],
      layout: { 'line-cap': 'round', 'line-join': 'round' },
      paint: { 'line-color': '#F2C86B', 'line-width': width([6, 0.8], [10, 2], [14, 6]) },
    },
    { id: 'rail', type: 'line', source: 'os', 'source-layer': 'rail', minzoom: 9, paint: { 'line-color': '#8B979C', 'line-width': 1, 'line-dasharray': [3, 3] } },
    {
      id: 'boundaries',
      type: 'line',
      source: 'os',
      'source-layer': 'boundaries',
      paint: { 'line-color': '#8B979C', 'line-width': 1, 'line-dasharray': [4, 3] },
    },
    {
      id: 'places',
      type: 'symbol',
      source: 'os',
      'source-layer': 'names',
      filter: ['in', ['get', 'type'], ['literal', SETTLEMENTS]],
      layout: {
        'text-field': ['get', 'name1'],
        'text-font': ['Noto Sans Medium'],
        'text-size': ['interpolate', ['linear'], ['zoom'], 8, 11, 14, 15],
        'text-max-width': 8,
      },
      paint: { 'text-color': '#26343B', 'text-halo-color': '#FFFFFF', 'text-halo-width': 1.6 },
    },
    {
      id: 'features',
      type: 'symbol',
      source: 'os',
      'source-layer': 'names',
      minzoom: 12,
      filter: ['!', ['in', ['get', 'type'], ['literal', SETTLEMENTS]]],
      layout: { 'text-field': ['get', 'name1'], 'text-font': ['Noto Sans Regular'], 'text-size': 12, 'text-max-width': 7 },
      paint: { 'text-color': '#44555D', 'text-halo-color': '#FFFFFF', 'text-halo-width': 1.4 },
    },
  ];
  return {
    version: 8,
    glyphs: `${origin}/map/fonts/{fontstack}/{range}.pbf`,
    sources: { os: { type: 'vector', url: `pmtiles://${origin}${TILES_PATH}`, attribution: ATTRIBUTION, maxzoom: 14 } },
    layers,
  };
}
