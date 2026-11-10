import { useId, useMemo, useState } from 'react';
import { ShapeIcon, STATUS_SHAPES } from '@/components/ui/StatusBadge';
import type { OptionView } from '@/lib/advisor/options';
import { layoutOf, PICTURE, percentOf, radiusPx } from '@/lib/map/layout';
import { KM_PER_DEGREE, type LatLon } from '@/lib/map/project';
import { overlappingPairs } from '@/lib/radar/radar';
import mapStyles from '../advisor/map.module.css';
import styles from './radar.module.css';
import { StyledSpan } from '@/components/ui/Styled';
import { TileMap, useWebgl, type TileArea, type TileMarker } from '@/components/map/TileMap';
import { lensRing } from '@/lib/map/geo';
import { Basemap, BASEMAP_ATTRIBUTION } from '../advisor/Basemap';
import { UnplacedNote } from '../advisor/UnplacedNote';

// The radar's picture (RadarWeb 1, 3 to 5): the patient's area at the postcode centre, each visiting service
// as an area, the overlap of two areas hatched, and each place to go as a labelled icon. Like the map
// (W50) it is a schematic, not a tile map: no tile provider is chosen and no third-party script is loaded.
// The picture is for the eye only: the key beside it and the list say the same in words, so nothing depends
// on seeing it. Areas differ by line as well as by colour: the first is solid, the others are dashed.

const PATIENT_RADIUS = 13;
const CAPTION = 'Schematic, not to scale. Patient shown at postcode centre. Each outlined area is where a visiting service can attend.';
const TILE_CAPTION = 'Patient shown at postcode centre. Each outlined area is where a visiting service can attend. Zoom and drag the map to look closer.';
const OFF_NOTE = 'Drive-time rings and traffic are off because there is no data behind them yet. They are not drawn from nothing.';

/** How the nth visiting service's area is drawn, here and in the key beside the picture. */
export type AreaStyle = { color: string; dash: string | undefined; fillOpacity: number };

const AREA_STYLES: readonly AreaStyle[] = [
  { color: 'var(--c-primary)', dash: undefined, fillOpacity: 0.16 },
  { color: 'var(--c-limited)', dash: '10 6', fillOpacity: 0.14 },
  { color: 'var(--c-surge)', dash: '3 5', fillOpacity: 0.12 },
  { color: 'var(--c-closed)', dash: '14 4 3 4', fillOpacity: 0.12 },
];

export function areaStyleOf(index: number): AreaStyle {
  return AREA_STYLES[index % AREA_STYLES.length];
}

export type RadarMapProps = {
  options: OptionView[];
  patientArea: LatLon | null;
  postcode: string;
};

function kindText(option: OptionView): string {
  if (option.coverage !== null) return 'Visits';
  if (option.position !== null) return 'Place to go';
  return 'No place on the map';
}

export function RadarMap({ options, patientArea, postcode }: RadarMapProps) {
  const uid = useId().replace(/[^A-Za-z0-9_-]/g, '');
  const hatch = `hatch-${uid}`;

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
  const pairs = overlappingPairs(options);

  const webgl = useWebgl();
  const [tilesFailed, setTilesFailed] = useState(false);
  const tiled = webgl && !tilesFailed;
  const showTiles = tiled && points.length > 0;
  const areas = useMemo<TileArea[]>(
    () =>
      visiting.map((option, index) => {
        const look = areaStyleOf(index);
        return {
          id: option.serviceId,
          centre: option.coverage as LatLon,
          radiusKm: (option.coverage as NonNullable<OptionView['coverage']>).radiusKm,
          color: look.color,
          dash: look.dash !== undefined,
          fillOpacity: look.fillOpacity,
        };
      }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [options],
  );
  const overlapRings = useMemo(
    () =>
      pairs
        .map(([first, second]) => lensRing({ ...(first.coverage as LatLon), radiusKm: first.coverage?.radiusKm ?? 0 }, { ...(second.coverage as LatLon), radiusKm: second.coverage?.radiusKm ?? 0 }))
        .filter((ring): ring is LatLon[] => ring !== null),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [options],
  );
  const label = (option: OptionView) => (
    <StyledSpan key={option.serviceId} className={styles.label} css={tiled ? {} : percentOf(centreOf(option))}>
      <ShapeIcon shape={STATUS_SHAPES[option.status]} />
      {option.name}
    </StyledSpan>
  );
  const markers: TileMarker[] = [
    ...(patientArea === null
      ? []
      : [
          {
            id: 'patient',
            at: patientArea,
            anchor: 'center' as const,
            node: (
              <span className={styles.patientMarker}>
                <span className={styles.patientDot} aria-hidden="true" />
                <span className={styles.patientTag}>{`Patient · ${postcode}`}</span>
              </span>
            ),
          },
        ]),
    ...fixed.map((option) => ({ id: option.serviceId, at: option.position as LatLon, anchor: 'center' as const, node: label(option) })),
    ...visiting.map((option) => ({ id: `${option.serviceId}-area`, at: option.coverage as LatLon, anchor: 'center' as const, node: label(option) })),
  ];
  const fit = [...points];

  return (
    <div className={styles.map}>
      <div className={mapStyles.picture} data-el="RADAR-PICTURE">
        {showTiles ? (
          <TileMap fit={fit} areas={areas} route={null} overlaps={overlapRings} markers={markers} onFailed={() => setTilesFailed(true)} />
        ) : (
          <>
          <svg className={mapStyles.svg} viewBox={`0 0 ${PICTURE.width} ${PICTURE.height}`} aria-hidden="true" focusable="false">
            <defs>
              <pattern id={hatch} width="8" height="8" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
                <line x1="0" y1="0" x2="0" y2="8" stroke="var(--c-ink)" strokeWidth="3" />
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
            <Basemap place={layout.place} />
            {visiting.map((option, index) => {
              const centre = centreOf(option);
              if (centre === undefined || option.coverage === null) return null;
              const look = areaStyleOf(index);
              return (
                <circle
                  key={option.serviceId}
                  cx={centre.x}
                  cy={centre.y}
                  r={radiusPx(option.coverage.radiusKm, layout.pxPerDegree)}
                  fill={look.color}
                  fillOpacity={look.fillOpacity}
                  stroke={look.color}
                  strokeWidth={3}
                  strokeDasharray={look.dash}
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
                  fillOpacity={0.55}
                  clipPath={`url(#${hatch}-${first.serviceId})`}
                  data-el="RADAR-OVERLAP"
                />
              );
            })}
            {patientArea === null ? null : (
              <circle cx={layout.points[0].x} cy={layout.points[0].y} r={PATIENT_RADIUS} fill="var(--c-ink)" stroke="#fff" strokeWidth={4} />
            )}
          </svg>

          {patientArea === null ? null : (
            <StyledSpan className={styles.patientLabel} css={percentOf(layout.points[0])}>
              {`Patient · ${postcode}`}
            </StyledSpan>
          )}
          {fixed.map((option) => {
            const centre = centreOf(option);
            return centre === undefined ? null : (
              <StyledSpan key={option.serviceId} className={styles.label} css={percentOf(centre)}>
                <ShapeIcon shape={STATUS_SHAPES[option.status]} />
                {option.name}
              </StyledSpan>
            );
          })}
          {visiting.map((option) => {
            const centre = centreOf(option);
            return centre === undefined ? null : (
              <StyledSpan key={option.serviceId} className={styles.label} css={percentOf(centre)}>
                <ShapeIcon shape={STATUS_SHAPES[option.status]} />
                {option.name}
              </StyledSpan>
            );
          })}
            <p className={styles.offNote} data-el="RADAR-OFF-NOTE">
              {OFF_NOTE}
            </p>
          </>
        )}
      </div>
      {showTiles ? (
        <p className={mapStyles.caption} data-el="RADAR-OFF-NOTE">
          {OFF_NOTE}
        </p>
      ) : null}
      <p className={mapStyles.caption}>{showTiles ? TILE_CAPTION : CAPTION}</p>
      <UnplacedNote options={options} className={mapStyles.caption} />
      {showTiles ? null : <p className={mapStyles.caption}>{BASEMAP_ATTRIBUTION}</p>}
      <ul className={styles.srOnly} aria-label={`Services near ${postcode}`}>
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
