import { useId } from 'react';
import { ShapeIcon, STATUS_SHAPES } from '@/components/ui/StatusBadge';
import type { OptionView } from '@/lib/advisor/options';
import { layoutOf, PICTURE, percentOf, radiusPx } from '@/lib/map/layout';
import { KM_PER_DEGREE, type LatLon } from '@/lib/map/project';
import { inLayer, type Layer, overlappingPairs } from '@/lib/radar/radar';
import mapStyles from '../advisor/map.module.css';
import styles from './radar.module.css';

// The radar's picture (RadarWeb 1, 3 to 5): the patient's area at the postcode centre, each visiting service
// as a dashed area, the overlap of two areas hatched, and each place to go as a labelled icon. Like the map
// (W50) it is a schematic, not a tile map: no tile provider is chosen and no third-party script is loaded.
// The picture is for the eye only: the list below it says the same in words, so nothing depends on seeing it.

const PATIENT_RADIUS = 9;
const CAPTION = 'Schematic, not to scale. Patient shown at postcode centre. Dashed areas are where a visiting service can attend.';

export type RadarMapProps = {
  options: OptionView[];
  patientArea: LatLon | null;
  /** The layers drawn. Every service stays in the list whether or not its layer is on. */
  layers: ReadonlySet<Layer>;
  postcode: string;
};

function kindText(option: OptionView): string {
  if (option.coverage !== null) return 'Visits';
  if (option.position !== null) return 'Place to go';
  return 'No place on the map';
}

export function RadarMap({ options, patientArea, layers, postcode }: RadarMapProps) {
  const uid = useId().replace(/[^A-Za-z0-9_-]/g, '');
  const hatch = `hatch-${uid}`;
  const shown = (option: OptionView) => [...layers].some((layer) => inLayer(option, layer));

  const visiting = options.filter((option) => option.coverage !== null);
  const fixed = options.filter((option) => option.position !== null);
  // The picture is fitted to every service, so turning a layer off does not move the others.
  const points = [
    ...(patientArea === null ? [] : [patientArea]),
    ...fixed.map((option) => option.position as LatLon),
    ...visiting.map((option) => option.coverage as LatLon),
    // The edges of every area, after the places above (their indexes are kept), so the picture holds whole
    // areas and not only their centres: a 15 km area drawn on a picture fitted to centres 3 km apart is a flood.
    ...visiting.flatMap((option) => {
      const { lat, lon, radiusKm } = option.coverage as NonNullable<OptionView['coverage']>;
      const dLat = radiusKm / KM_PER_DEGREE;
      const dLon = dLat / Math.max(0.1, Math.cos((lat * Math.PI) / 180));
      return [
        { lat: lat + dLat, lon },
        { lat: lat - dLat, lon },
        { lat, lon: lon + dLon },
        { lat, lon: lon - dLon },
      ];
    }),
  ];
  const layout = layoutOf(points);
  const offset = patientArea === null ? 0 : 1;
  const centreOf = (option: OptionView) => {
    const index = fixed.includes(option) ? offset + fixed.indexOf(option) : offset + fixed.length + visiting.indexOf(option);
    return layout.points[index];
  };
  const pairs = overlappingPairs(options).filter(([a, b]) => shown(a) && shown(b));

  return (
    <div className={styles.map}>
      <div className={mapStyles.picture} data-el="RADAR-PICTURE">
        <svg className={mapStyles.svg} viewBox={`0 0 ${PICTURE.width} ${PICTURE.height}`} aria-hidden="true" focusable="false">
          <defs>
            <pattern id={hatch} width="8" height="8" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
              <line x1="0" y1="0" x2="0" y2="8" stroke="currentColor" strokeWidth="3" />
            </pattern>
            {pairs.map(([first]) => {
              const centre = centreOf(first);
              if (centre === undefined || first.coverage === null) return null;
              return (
                <clipPath key={first.serviceId} id={`${hatch}-${first.serviceId}`}>
                  <circle cx={centre.x} cy={centre.y} r={radiusPx(first.coverage.radiusKm, layout.pxPerDegree)} />
                </clipPath>
              );
            })}
          </defs>
          {visiting.filter(shown).map((option) => {
            const centre = centreOf(option);
            if (centre === undefined || option.coverage === null) return null;
            return (
              <circle
                key={option.serviceId}
                cx={centre.x}
                cy={centre.y}
                r={radiusPx(option.coverage.radiusKm, layout.pxPerDegree)}
                fill="currentColor"
                fillOpacity={0.08}
                stroke="currentColor"
                strokeWidth={2}
                strokeDasharray="6 6"
                data-el={`RADAR-AREA-${option.serviceId.toUpperCase()}`}
              />
            );
          })}
          {pairs.map(([first, second]) => {
            const centre = centreOf(second);
            if (centre === undefined || second.coverage === null) return null;
            return (
              <circle
                key={`${first.serviceId}-${second.serviceId}`}
                cx={centre.x}
                cy={centre.y}
                r={radiusPx(second.coverage.radiusKm, layout.pxPerDegree)}
                fill={`url(#${hatch})`}
                fillOpacity={0.35}
                clipPath={`url(#${hatch}-${first.serviceId})`}
                data-el="RADAR-OVERLAP"
              />
            );
          })}
          {patientArea === null ? null : (
            <circle cx={layout.points[0].x} cy={layout.points[0].y} r={PATIENT_RADIUS} fill="currentColor" />
          )}
        </svg>

        {patientArea === null ? null : (
          <span className={mapStyles.visiting} style={percentOf(layout.points[0])}>
            Patient area
          </span>
        )}
        {fixed.filter(shown).map((option) => {
          const centre = centreOf(option);
          return centre === undefined ? null : (
            <span key={option.serviceId} className={styles.label} style={percentOf(centre)}>
              <ShapeIcon shape={STATUS_SHAPES[option.status]} />
              {option.name}
            </span>
          );
        })}
        {visiting.filter(shown).map((option) => {
          const centre = centreOf(option);
          return centre === undefined ? null : (
            <span key={option.serviceId} className={styles.label} style={percentOf(centre)}>
              <ShapeIcon shape={STATUS_SHAPES[option.status]} />
              {option.name}
            </span>
          );
        })}
      </div>
      <p className={mapStyles.caption}>{CAPTION}</p>
      <ul className={styles.keyList} aria-label={`Services near ${postcode}`}>
        {options.map((option) => (
          <li key={option.serviceId}>
            <strong>{option.name}</strong>
            {`: ${kindText(option)}`}
            {option.coverage === null ? '' : `, area radius about ${Math.round(option.coverage.radiusKm)} km`}
          </li>
        ))}
      </ul>
    </div>
  );
}
