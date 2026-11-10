import { describe, expect, it } from 'vitest';
import { areaEdges, circleRing, lensRing } from './geo';
import { KM_PER_DEGREE } from './project';

const centre = { lat: 50.7, lon: -2.4 };

describe('map shapes (DEC-1362)', () => {
  it('draws a closed ring whose points are one radius from the centre', () => {
    const ring = circleRing(centre, 10);
    expect(ring[0]).toEqual(ring[ring.length - 1]);
    const [lon, lat] = ring[18];
    const dy = (lat - centre.lat) * KM_PER_DEGREE;
    const dx = (lon - centre.lon) * Math.cos((centre.lat * Math.PI) / 180) * KM_PER_DEGREE;
    expect(Math.hypot(dx, dy)).toBeCloseTo(10, 1);
  });

  it('gives the four edges of an area for fitting the view', () => {
    const edges = areaEdges(centre, 11.1);
    expect(edges).toHaveLength(4);
    expect(edges[0].lat).toBeCloseTo(centre.lat + 0.1, 6);
    expect(edges[1].lat).toBeCloseTo(centre.lat - 0.1, 6);
  });

  it('finds the ground two areas share, inside both, and none for areas apart', () => {
    const a = { ...centre, radiusKm: 10 };
    const b = { lat: centre.lat, lon: centre.lon + 0.2, radiusKm: 10 };
    const lens = lensRing(a, b);
    expect(lens).not.toBeNull();
    const lons = (lens ?? []).map((point) => point.lon);
    expect(Math.min(...lons)).toBeGreaterThan(a.lon);
    expect(Math.max(...lons)).toBeLessThan(b.lon);
    expect(lensRing(a, { lat: 51.5, lon: -1.0, radiusKm: 5 })).toBeNull();
  });
});
