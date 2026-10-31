import type { Coverage } from '@/lib/advisor/options';
import type { LatLon } from '@/lib/map/project';

// The radar's geometry (docs: RadarWeb, "Radar: who covers this area"). A visiting service's area is a
// circle around its base, in kilometres (the back end's coverage circle, domain/rules/coverage.py), and
// the patient is a point at the postcode centre. Pure.

const EARTH_RADIUS_KM = 6371;
const RADIANS = Math.PI / 180;

/** The great-circle distance between two places, in kilometres (haversine). */
export function distanceKm(a: LatLon, b: LatLon): number {
  const dLat = (b.lat - a.lat) * RADIANS;
  const dLon = (b.lon - a.lon) * RADIANS;
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(a.lat * RADIANS) * Math.cos(b.lat * RADIANS) * Math.sin(dLon / 2) ** 2;
  return 2 * EARTH_RADIUS_KM * Math.asin(Math.min(1, Math.sqrt(h)));
}

/** True when the point is inside the area, edge included. */
export function covers(area: Coverage, point: LatLon): boolean {
  return distanceKm(area, point) <= area.radiusKm;
}

/** True when the two areas share ground: their centres are closer than the radii added. */
export function overlaps(a: Coverage, b: Coverage): boolean {
  return distanceKm(a, b) < a.radiusKm + b.radiusKm;
}
