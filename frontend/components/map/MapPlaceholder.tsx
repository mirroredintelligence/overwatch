import { Basemap } from '@/components/advisor/Basemap';
import { Loading, Skeleton } from '@/components/ui/Skeleton';
import { layoutOf, PICTURE } from '@/lib/map/layout';
import type { LatLon } from '@/lib/map/project';
import styles from './mapPlaceholder.module.css';

// What the map's box shows while the zoomable map loads (DEC-1371): the bundled land outlines as pale shapes, faint
// grid and road lines, a few pale pins and the bars a legend would have, and the words "Loading the map". It fills
// the same box as the map, so nothing moves when the map arrives and this is taken away. The outline is the
// schematic's own projection of the same places, a likeness of the first view and not its exact framing.
// Nothing in it needs the network or a style attribute; under reduced motion nothing in it moves.

const GRID = [100, 200, 300, 400, 500];
const ROADS = ['M0 300 C150 270 260 330 380 250 S560 200 600 150', 'M120 0 C140 120 200 200 190 400', 'M0 90 L600 130'];
const MAX_PINS = 5;

export function MapPlaceholder({ fit }: { fit: LatLon[] }) {
  const layout = layoutOf(fit);
  const pins = layout.points.slice(0, MAX_PINS);
  return (
    <div className={styles.placeholder} data-el="MAP-LOADING">
      <Loading label="Loading the map.">
        <svg className={styles.svg} viewBox={`0 0 ${PICTURE.width} ${PICTURE.height}`} aria-hidden="true" focusable="false" preserveAspectRatio="xMidYMid slice">
          <g className={styles.land}>
            {fit.length === 0 ? null : <Basemap place={layout.place} />}
          </g>
          <g className={styles.lines}>
            {GRID.map((x) => (
              <line key={`x${x}`} x1={x} y1={0} x2={x} y2={PICTURE.height} />
            ))}
            {GRID.slice(0, 3).map((y) => (
              <line key={`y${y}`} x1={0} y1={y} x2={PICTURE.width} y2={y} />
            ))}
          </g>
          <g className={styles.roads}>
            {ROADS.map((d) => (
              <path key={d} d={d} />
            ))}
          </g>
          <g className={styles.pins}>
            {pins.map((point, index) => (
              <circle key={index} cx={point.x} cy={point.y} r={9} data-pin />
            ))}
          </g>
        </svg>
        <div className={styles.bars}>
          <Skeleton shape="line" width="52%" />
          <Skeleton shape="line" width="34%" />
        </div>
        <span className={styles.word} data-el="MAP-LOADING-WORD">
          Loading the map…
        </span>
      </Loading>
    </div>
  );
}
