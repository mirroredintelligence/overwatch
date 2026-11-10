import { describe, expect, it } from 'vitest';
import { captionOf } from './caption';

// The words under the map say only what is drawn (DEC-1372): no patient marker, no sentence about one.

const base = { patient: false, visiting: false, route: false, coverage: false, tiles: true };

describe('captionOf', () => {
  it('names the patient area only when it is drawn', () => {
    expect(captionOf({ ...base, patient: true })).toMatch(/patient's area is marked at the postcode centre/i);
    expect(captionOf({ ...base, patient: false })).not.toMatch(/patient/i);
  });

  it('says nothing about areas or the route when none is drawn', () => {
    const text = captionOf({ ...base, patient: true });
    expect(text).not.toMatch(/dashed|outlined|area is where|route/i);
  });

  it('describes visiting areas by line, and the overlap only with the coverage layer on', () => {
    expect(captionOf({ ...base, visiting: true })).toMatch(/Dashed areas are where a visiting service can attend/);
    const layer = captionOf({ ...base, visiting: true, coverage: true });
    expect(layer).toMatch(/Outlined areas are where a visiting service can attend/);
    expect(layer).toMatch(/hatched/);
    expect(captionOf({ ...base, visiting: true })).not.toMatch(/hatched/);
  });

  it('mentions the route only when there is one', () => {
    expect(captionOf({ ...base, route: true })).toMatch(/dotted line is the route to the selected site/);
    expect(captionOf(base)).not.toMatch(/dotted/);
  });

  it('says zoom for the tile map and schematic for the fallback', () => {
    expect(captionOf({ ...base, tiles: true })).toMatch(/Zoom and drag/);
    expect(captionOf({ ...base, tiles: false })).toMatch(/Schematic, not to scale/);
    expect(captionOf({ ...base, tiles: false })).not.toMatch(/Zoom/);
  });
});
