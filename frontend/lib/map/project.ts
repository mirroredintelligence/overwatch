// The schematic map's projection (W50): latitude and longitude onto a picture, equirectangular and
// fitted to the points' bounding box, with one scale on both axes so distances keep their shape. Pure.

export type LatLon = { lat: number; lon: number };
export type Point = { x: number; y: number };

/** A degree of latitude, in kilometres (the length of a degree of longitude is scaled by cos of latitude). */
export const KM_PER_DEGREE = 111;

const RADIANS = Math.PI / 180;

export type Projection = { points: Point[]; pxPerDegree: number };

/**
 * Projects the points into a width by height picture with the given padding. The bounding box is
 * scaled uniformly to fit and centred. `pxPerDegree` is the picture length of one degree of latitude,
 * which the coverage areas use to draw their radius.
 */
export function projectFit(points: LatLon[], width: number, height: number, padding = 0): Projection {
  if (points.length === 0) return { points: [], pxPerDegree: 0 };
  const lats = points.map((point) => point.lat);
  const lons = points.map((point) => point.lon);
  const minLat = Math.min(...lats);
  const maxLat = Math.max(...lats);
  const minLon = Math.min(...lons);
  const maxLon = Math.max(...lons);

  const kx = Math.cos(((minLat + maxLat) / 2) * RADIANS);
  const spanX = (maxLon - minLon) * kx;
  const spanY = maxLat - minLat;
  const usableWidth = Math.max(0, width - 2 * padding);
  const usableHeight = Math.max(0, height - 2 * padding);
  const fitX = spanX > 0 ? usableWidth / spanX : Infinity;
  const fitY = spanY > 0 ? usableHeight / spanY : Infinity;
  const scale = Number.isFinite(Math.min(fitX, fitY)) ? Math.min(fitX, fitY) : 0;

  const offsetX = padding + (usableWidth - spanX * scale) / 2;
  const offsetY = padding + (usableHeight - spanY * scale) / 2;
  return {
    points: points.map((point) => ({
      x: offsetX + (point.lon - minLon) * kx * scale,
      y: offsetY + (maxLat - point.lat) * scale,
    })),
    pxPerDegree: scale,
  };
}

/** The points only, for callers that need no scale. */
export function project(points: LatLon[], width: number, height: number, padding = 0): Point[] {
  return projectFit(points, width, height, padding).points;
}
