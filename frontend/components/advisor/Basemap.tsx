import { LAND_RINGS } from '@/lib/map/landRings';
import type { LatLon, Point } from '@/lib/map/project';

// The land under the schematic (DEC-1361): ONS district outlines bundled with the app and drawn as SVG paths
// with the picture's own projection, so the coast and the district lines show with no tile server and no
// third-party request. The sea is the picture's background. Drawn first, behind the areas and the pins.

const PATHS: readonly (readonly LatLon[])[] = LAND_RINGS.map((ring) =>
  ring.split(' ').map((pair) => {
    const [lon, lat] = pair.split(',').map(Number);
    return { lat, lon };
  }),
);

/** The licence's attribution line (OGL v3.0), shown with every picture that draws the land. */
export const BASEMAP_ATTRIBUTION = 'Land outlines: Office for National Statistics, Open Government Licence v3.0.';

export function Basemap({ place }: { place: (point: LatLon) => Point }) {
  const d = PATHS.map(
    (ring) => `${ring.map((point, index) => `${index === 0 ? 'M' : 'L'}${place(point).x.toFixed(1)} ${place(point).y.toFixed(1)}`).join('')}Z`,
  ).join('');
  return (
    <path
      d={d}
      fill="var(--c-bg)"
      stroke="var(--c-muted)"
      strokeOpacity={0.55}
      strokeWidth={1.25}
      strokeLinejoin="round"
      data-el="ADV-MAP-LAND"
    />
  );
}
