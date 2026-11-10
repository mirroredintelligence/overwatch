import { KM_PER_DEGREE, type LatLon } from './project';

// Shapes for the tile map (DEC-1362). Pure.

const STEPS = 72;

/** A coverage circle as a closed GeoJSON ring of [lon, lat], on a flat earth that is good for tens of km. */
export function circleRing(centre: LatLon, radiusKm: number): [number, number][] {
  const dLat = radiusKm / KM_PER_DEGREE;
  const dLon = dLat / Math.max(0.1, Math.cos((centre.lat * Math.PI) / 180));
  const ring: [number, number][] = [];
  for (let step = 0; step < STEPS; step += 1) {
    const angle = (step / STEPS) * 2 * Math.PI;
    ring.push([centre.lon + dLon * Math.cos(angle), centre.lat + dLat * Math.sin(angle)]);
  }
  ring.push(ring[0]);
  return ring;
}

/** The four edges of a coverage circle, so a map fitted to the points holds whole areas and not only their centres. */
export function areaEdges(centre: LatLon, radiusKm: number): LatLon[] {
  const dLat = radiusKm / KM_PER_DEGREE;
  const dLon = dLat / Math.max(0.1, Math.cos((centre.lat * Math.PI) / 180));
  return [
    { lat: centre.lat + dLat, lon: centre.lon },
    { lat: centre.lat - dLat, lon: centre.lon },
    { lat: centre.lat, lon: centre.lon + dLon },
    { lat: centre.lat, lon: centre.lon - dLon },
  ];
}

const LENS_STEPS = 180;

type Circle = { lat: number; lon: number; radiusKm: number };

/** The ground two coverage circles share, as a ring of lat/lon: the arc of each circle that lies inside the other. Null when they share none. */
export function lensRing(a: Circle, b: Circle): LatLon[] | null {
  const kx = Math.max(0.1, Math.cos((a.lat * Math.PI) / 180));
  const toKm = (point: LatLon) => ({ x: (point.lon - a.lon) * kx * KM_PER_DEGREE, y: (point.lat - a.lat) * KM_PER_DEGREE });
  const fromKm = (x: number, y: number): LatLon => ({ lat: a.lat + y / KM_PER_DEGREE, lon: a.lon + x / (kx * KM_PER_DEGREE) });
  const centreB = toKm(b);
  const inside: { x: number; y: number }[] = [];
  for (let step = 0; step < LENS_STEPS; step += 1) {
    const angle = (step / LENS_STEPS) * 2 * Math.PI;
    const onA = { x: a.radiusKm * Math.cos(angle), y: a.radiusKm * Math.sin(angle) };
    if (Math.hypot(onA.x - centreB.x, onA.y - centreB.y) <= b.radiusKm) inside.push(onA);
    const onB = { x: centreB.x + b.radiusKm * Math.cos(angle), y: centreB.y + b.radiusKm * Math.sin(angle) };
    if (Math.hypot(onB.x, onB.y) <= a.radiusKm) inside.push(onB);
  }
  if (inside.length < 3) return null;
  const cx = inside.reduce((sum, point) => sum + point.x, 0) / inside.length;
  const cy = inside.reduce((sum, point) => sum + point.y, 0) / inside.length;
  inside.sort((p, q) => Math.atan2(p.y - cy, p.x - cx) - Math.atan2(q.y - cy, q.x - cx));
  return inside.map((point) => fromKm(point.x, point.y));
}
