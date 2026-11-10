// How the nth visiting service's area is drawn on the map's "who covers this area" layer, and in the key beside
// it: the first is solid, the others dashed differently, so areas differ by line as well as by colour.

export type AreaStyle = { color: string; dash: string | undefined; fillOpacity: number };

const AREA_STYLES: readonly AreaStyle[] = [
  { color: 'var(--c-primary)', dash: undefined, fillOpacity: 0.16 },
  { color: 'var(--c-limited)', dash: '10 6', fillOpacity: 0.14 },
  { color: 'var(--c-surge)', dash: '3 5', fillOpacity: 0.12 },
  { color: 'var(--c-closed)', dash: '14 4 3 4', fillOpacity: 0.12 },
];

export function areaStyleOf(index: number): AreaStyle {
  return AREA_STYLES[index % AREA_STYLES.length];
}
