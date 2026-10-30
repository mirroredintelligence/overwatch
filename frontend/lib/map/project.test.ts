import { describe, expect, it } from 'vitest';
import { project, projectFit } from './project';

describe('project (W50)', () => {
  it('maps the corners of a box that fills the picture to the picture corners', () => {
    // A box one degree of latitude by two of longitude at the equator: 2:1, as the picture is.
    const box = [
      { lat: 0, lon: 0 },
      { lat: 1, lon: 2 },
    ];
    const [bottomLeft, topRight] = project(box, 200, 100);

    expect(bottomLeft.x).toBeCloseTo(0, 6);
    expect(bottomLeft.y).toBeCloseTo(100, 6);
    expect(topRight.x).toBeCloseTo(200, 6);
    expect(topRight.y).toBeCloseTo(0, 6);
  });

  it('keeps the aspect ratio: one kilometre is the same length east-west and north-south', () => {
    const points = [
      { lat: 50, lon: -2 },
      { lat: 50.1, lon: -1.9 },
      { lat: 50.05, lon: -2.1 },
    ];
    const fit = projectFit(points, 400, 300);
    const [a, b] = fit.points;
    const dy = Math.abs(a.y - b.y);
    const dx = Math.abs(a.x - b.x);
    // A degree of latitude is the same length on the picture as a degree of longitude times cos(lat).
    expect(dx / dy).toBeCloseTo((0.1 / 0.1) * Math.cos((50.05 * Math.PI) / 180), 2);
    expect(fit.pxPerDegree).toBeGreaterThan(0);
  });

  it('keeps every point inside the picture, with the padding', () => {
    const points = [
      { lat: 50.6, lon: -2.6 },
      { lat: 50.8, lon: -2.2 },
      { lat: 50.7, lon: -2.4 },
    ];
    for (const { x, y } of project(points, 300, 200, 10)) {
      expect(x).toBeGreaterThanOrEqual(10 - 1e-9);
      expect(x).toBeLessThanOrEqual(290 + 1e-9);
      expect(y).toBeGreaterThanOrEqual(10 - 1e-9);
      expect(y).toBeLessThanOrEqual(190 + 1e-9);
    }
  });

  it('a single point, or none, is placed at the centre and gives none', () => {
    expect(project([{ lat: 50.7, lon: -2.4 }], 200, 100)).toEqual([{ x: 100, y: 50 }]);
    expect(project([], 200, 100)).toEqual([]);
  });
});
