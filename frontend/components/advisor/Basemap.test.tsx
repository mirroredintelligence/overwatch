import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { layoutOf, MIN_SPAN_DEGREES, PICTURE } from '@/lib/map/layout';
import { LAND_RINGS } from '@/lib/map/landRings';
import { Basemap } from './Basemap';

const DT4 = { lat: 50.6, lon: -2.46 };

describe('Basemap (DEC-1361)', () => {
  it('draws the bundled land as one path in the picture, with no network request', () => {
    const layout = layoutOf([DT4]);
    const { container } = render(
      <svg>
        <Basemap place={layout.place} />
      </svg>,
    );
    const path = container.querySelector('[data-el="ADV-MAP-LAND"]');
    expect(path).not.toBeNull();
    expect((path?.getAttribute('d')?.match(/M/g) ?? []).length).toBe(LAND_RINGS.length);
    expect(container.querySelector('image, foreignObject, script')).toBeNull();
  });

  it('keeps a lone patient point in a window about 22 km tall, so the land is not a flood', () => {
    const layout = layoutOf([DT4]);
    expect(layout.points).toHaveLength(1);
    expect(layout.pxPerDegree * MIN_SPAN_DEGREES).toBeLessThanOrEqual(PICTURE.height);
    expect(layout.pxPerDegree).toBeGreaterThan(0);
    // Weymouth's coast, 0.15 degrees south, lands inside the picture.
    const south = layout.place({ lat: DT4.lat - 0.09, lon: DT4.lon });
    expect(south.y).toBeLessThan(PICTURE.height);
  });

  it('does not change a layout of points already wider than the window', () => {
    const a = layoutOf([DT4, { lat: 50.9, lon: -2.0 }]);
    expect(a.points[0].x).toBeGreaterThanOrEqual(PICTURE.padding - 0.001);
  });
});
