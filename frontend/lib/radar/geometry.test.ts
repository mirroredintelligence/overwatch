import { describe, expect, it } from 'vitest';
import { covers, distanceKm, overlaps } from './geometry';

describe('distanceKm', () => {
  it('is zero for the same place', () => {
    expect(distanceKm({ lat: 50.7, lon: -2.44 }, { lat: 50.7, lon: -2.44 })).toBe(0);
  });

  it('is about 111 km for one degree of latitude', () => {
    expect(distanceKm({ lat: 50, lon: 0 }, { lat: 51, lon: 0 })).toBeCloseTo(111.2, 0);
  });

  it('is shorter along a parallel than along a meridian at the same angle', () => {
    const along = distanceKm({ lat: 50, lon: 0 }, { lat: 50, lon: 1 });
    expect(along).toBeLessThan(111);
    expect(along).toBeCloseTo(71.5, 0);
  });

  it('is the same both ways', () => {
    const a = { lat: 50.72, lon: -2.45 };
    const b = { lat: 50.69, lon: -2.4 };
    expect(distanceKm(a, b)).toBeCloseTo(distanceKm(b, a), 10);
  });
});

describe('covers and overlaps', () => {
  const west = { lat: 50.72, lon: -2.45, radiusKm: 12 };

  it('a point inside the circle is covered, a point outside is not', () => {
    expect(covers(west, { lat: 50.71, lon: -2.44 })).toBe(true);
    expect(covers(west, { lat: 51.2, lon: -1.2 })).toBe(false);
  });

  it('the edge counts as inside', () => {
    const edge = { lat: west.lat + west.radiusKm / 111.195, lon: west.lon };
    expect(covers({ ...west, radiusKm: distanceKm(west, edge) }, edge)).toBe(true);
  });

  it('two circles overlap when their centres are closer than the radii added', () => {
    expect(overlaps(west, { lat: 50.7, lon: -2.3, radiusKm: 14 })).toBe(true);
    expect(overlaps(west, { lat: 51.2, lon: -1.2, radiusKm: 5 })).toBe(false);
  });

  it('two circles just further apart than the radii added do not share ground', () => {
    const a = { lat: 50, lon: 0, radiusKm: 10 };
    const b = { lat: 50 + 20.5 / 111.195, lon: 0, radiusKm: 10 };
    expect(overlaps(a, b)).toBe(false);
  });
});
