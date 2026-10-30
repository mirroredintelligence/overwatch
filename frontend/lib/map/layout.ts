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
export function layoutOf(points: LatLon[]): { points: Point[]; pxPerDegree: number } {
  return projectFit(points, PICTURE.width, PICTURE.height, PICTURE.padding);
}

/** A coverage radius in picture units, from kilometres and the picture's scale. */
export function radiusPx(radiusKm: number, pxPerDegree: number): number {
  return (radiusKm / KM_PER_DEGREE) * pxPerDegree;
}
