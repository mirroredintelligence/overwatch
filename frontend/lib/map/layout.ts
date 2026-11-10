import { KM_PER_DEGREE, projectFit, type LatLon, type Point } from './project';

// The picture's size in its own units, and the padding inside it. The pins are placed by percentage of
// the picture, so the picture can scale to any width without the pins moving off their places.
export const PICTURE = { width: 600, height: 400, padding: 36 } as const;

export type Placed<T> = { item: T; point: Point };

/** Places a point, with the picture's own scale, as a percentage of the picture (for the pins). */
export function percentOf(point: Point): { left: string; top: string } {
  return {
    left: `${(point.x / PICTURE.width) * 100}%`,
    top: `${(point.y / PICTURE.height) * 100}%`,
  };
}

/** Projects the points of the picture and reports the picture's scale in units per degree of latitude. */
export function layoutOf(points: LatLon[]): { points: Point[]; pxPerDegree: number; place: (point: LatLon) => Point } {
  const fit = projectFit([...points, ...minimumWindow(points)], PICTURE.width, PICTURE.height, PICTURE.padding);
  return { points: fit.points.slice(0, points.length), pxPerDegree: fit.pxPerDegree, place: fit.place };
}

/** The smallest area the picture shows, in degrees of latitude: about 22 km, so a lone patient dot still has a coast around it. */
export const MIN_SPAN_DEGREES = 0.2;

/** Four corners that widen a box smaller than the smallest area to it, centred; none when the box is big enough. */
function minimumWindow(points: LatLon[]): LatLon[] {
  if (points.length === 0) return [];
  const lats = points.map((point) => point.lat);
  const lons = points.map((point) => point.lon);
  const lat = (Math.min(...lats) + Math.max(...lats)) / 2;
  const lon = (Math.min(...lons) + Math.max(...lons)) / 2;
  const halfLat = MIN_SPAN_DEGREES / 2;
  const halfLon = (MIN_SPAN_DEGREES * 1.5) / 2 / Math.max(0.1, Math.cos((lat * Math.PI) / 180));
  return [
    { lat: lat + halfLat, lon: lon + halfLon },
    { lat: lat - halfLat, lon: lon - halfLon },
  ];
}

/** A coverage radius in picture units, from kilometres and the picture's scale. */
export function radiusPx(radiusKm: number, pxPerDegree: number): number {
  return (radiusKm / KM_PER_DEGREE) * pxPerDegree;
}
