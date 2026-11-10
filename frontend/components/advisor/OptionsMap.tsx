'use client';

import { useId, useMemo, useState, type CSSProperties } from 'react';
import { Button } from '@/components/ui/Button';
import { ShapeIcon, STATUS_SHAPES, StatusBadge } from '@/components/ui/StatusBadge';
import type { LatLon } from '@/lib/map/project';
import { layoutOf, PICTURE, percentOf, radiusPx } from '@/lib/map/layout';
import { type OptionView } from '@/lib/advisor/options';
import { durationText } from '@/lib/board/format';
import { TileMap, useWebgl, type TileArea, type TileMarker } from '@/components/map/TileMap';
import { areaEdges, lensRing } from '@/lib/map/geo';
import { areaStyleOf } from '@/lib/map/areaStyle';
import { captionOf } from '@/lib/map/caption';
import { outwardCode } from '@/lib/advisor/postcode';
import { overlappingPairs } from '@/lib/radar/radar';
import { Basemap, BASEMAP_ATTRIBUTION } from './Basemap';
import { CoveragePanel } from './CoveragePanel';
import { NetworkServiceLine } from './NetworkServiceLine';
import { OptionBooking } from './OptionBooking';
import { numberText } from './ServiceCard';
import { ServicePhone } from './ServicePhone';
import { TravelDetails } from './TravelDetails';
import { UnplacedNote } from './UnplacedNote';
import styles from './MapScreen.module.css';
import { StyledButton, StyledSpan } from '@/components/ui/Styled';

// The options drawn as a schematic (W50, Map board): the patient's area at the postcode centre, each fixed
// site as a labelled pin, and each visiting service as a dashed area. It is not a tile map: no tile provider
// is chosen and no third-party script is loaded. The list holds every service the map shows.

export type OptionsMapProps = {
  caseId: string;
  postcode: string;
  patientArea: LatLon | null;
  options: OptionView[];
  selectedId: string | null;
  onSelect: (serviceId: string) => void;
  onCriteria?: (serviceId: string) => void;
  /** The dialog for another organisation's criteria (the network map only): see ServiceCard. */
  onNetworkCriteria?: (serviceId: string) => void;
  /** The "Who covers this area" layer starts on (the address asked for it). */
  initialCoverage?: boolean;
};

function freeText(option: OptionView): string | null {
  if (option.effectiveAvailable === null) return null;
  const unit = (option.unitLabel ?? '').replace(/ free$/, '');
  return `Free ${option.effectiveAvailable}${unit === '' ? '' : ` ${unit}`}`;
}

function travelLine(option: OptionView): string {
  if (option.travel === null) return 'Travel not recorded';
  const { low, high } = option.travel;
  const range = low === high ? `${low} min` : `${low} to ${high} min`;
  return `Patient to ${option.name} by road ${range}`;
}

// The words on a pin: the name, and the free figure when there is one ("UCR West · 4", "Hospital at home · +2").
function pinText(name: string, option: OptionView): string {
  const figure = numberText(option);
  return figure === '?' ? name : `${name} · ${figure}`;
}

export function OptionsMap({
  caseId,
  postcode,
  patientArea,
  options,
  selectedId,
  onSelect,
  onCriteria,
  onNetworkCriteria,
  initialCoverage = false,
}: OptionsMapProps) {
  const uid = useId().replace(/[^A-Za-z0-9_-]/g, '');
  const hatch = `hatch-${uid}`;
  const [coverage, setCoverage] = useState(initialCoverage);
  const fixed = options.filter((option) => option.position !== null);
  const visiting = options.filter((option) => option.coverage !== null);
  const points = [
    ...(patientArea === null ? [] : [patientArea]),
    ...fixed.map((option) => option.position as LatLon),
    ...visiting.map((option) => option.coverage as LatLon),
  ];
  // The picture holds whole areas, not only their centres (the edges follow the places, so their indexes are kept).
  const edges = visiting.flatMap((option) => areaEdges(option.coverage as LatLon, (option.coverage as NonNullable<OptionView['coverage']>).radiusKm));
  const layout = layoutOf([...points, ...edges]);
  const at = (index: number) => layout.points[index];
  const offset = patientArea === null ? 0 : 1;
  const selected = options.find((option) => option.serviceId === selectedId) ?? null;
  // The zoomable map where the browser can draw it and the tiles answer; the schematic below otherwise (DEC-1362).
  const webgl = useWebgl();
  const [tilesFailed, setTilesFailed] = useState(false);
  const tiled = webgl && !tilesFailed;
  const showTiles = tiled && points.length > 0;
  // The route to the selected fixed site: a dotted line from the patient (W50, MapWeb). A visiting service
  // comes to the patient, so it has no route to draw.
  const selectedIndex = selected === null ? -1 : fixed.findIndex((option) => option.serviceId === selected.serviceId);
  const routeEnd = selectedIndex < 0 || patientArea === null ? null : at(offset + selectedIndex);

  const outward = outwardCode(postcode);
  const patientLabel = outward === null ? 'Patient area' : `Patient area · ${outward}`;
  const pinCss = (index: number) => (tiled ? {} : percentOf(at(index)));
  const patientEl = (css: CSSProperties) => (
    <StyledSpan className={styles.patient} css={css}>
      <span className={styles.patientDot} aria-hidden="true" />
      <span className={styles.patientLabel}>{patientLabel}</span>
    </StyledSpan>
  );
  const pinEl = (option: OptionView, css: CSSProperties, visits: boolean) => (
    <StyledButton
      key={option.serviceId}
      type="button"
      className={styles.pin}
      css={css}
      aria-label={visits ? `${option.name} (visits)` : option.name}
      aria-pressed={option.serviceId === selectedId}
      data-status={option.status}
      data-el={`${visits ? 'ADV-MAP-AREA-' : 'ADV-MAP-PIN-'}${option.serviceId.toUpperCase()}`}
      onClick={() => onSelect(option.serviceId)}
    >
      <span className={styles.marker} aria-hidden="true">
        <ShapeIcon shape={STATUS_SHAPES[option.status]} />
      </span>
      <span className={styles.label}>{pinText(visits ? `${option.name} (visits)` : option.name, option)}</span>
    </StyledButton>
  );

  const areas = useMemo<TileArea[]>(
    () =>
      visiting.map((option, index) => {
        const look = coverage ? areaStyleOf(index) : { color: 'var(--c-primary)', dash: '3 2', fillOpacity: 0.1 };
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
    [options, coverage],
  );
  const pairs = coverage ? overlappingPairs(options) : [];
  const lenses = pairs
    .map(([first, second]) => lensRing({ ...(first.coverage as LatLon), radiusKm: first.coverage?.radiusKm ?? 0 }, { ...(second.coverage as LatLon), radiusKm: second.coverage?.radiusKm ?? 0 }))
    .filter((ring): ring is LatLon[] => ring !== null);
  const overlapRings = useMemo(
    () => lenses,
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [options, coverage],
  );
  const fit = [...points, ...edges];
  const tileRoute: [LatLon, LatLon] | null =
    selectedIndex < 0 || patientArea === null ? null : [patientArea, fixed[selectedIndex].position as LatLon];
  const markers: TileMarker[] = [
    ...(patientArea === null ? [] : [{ id: 'patient', at: patientArea, anchor: 'bottom' as const, node: patientEl({}) }]),
    ...fixed.map((option) => ({ id: option.serviceId, at: option.position as LatLon, anchor: 'bottom' as const, node: pinEl(option, {}, false) })),
    ...visiting.map((option) => ({ id: `${option.serviceId}-area`, at: option.coverage as LatLon, anchor: 'bottom' as const, node: pinEl(option, {}, true) })),
  ];

  return (
    <section className={styles.mapWrap} aria-label={`Map of options near ${postcode}`}>
      <div className={styles.layerRow}>
        <button type="button" className={styles.layerToggle} aria-pressed={coverage} data-el="ADV-MAP-LAYER-COVERAGE" onClick={() => setCoverage((on) => !on)}>
          Who covers this area
        </button>
      </div>
      <div className={styles.mapCard}>
        <div className={styles.picture}>
          {showTiles ? (
            <TileMap fit={fit} areas={areas} route={tileRoute} overlaps={overlapRings} markers={markers} onFailed={() => setTilesFailed(true)} />
          ) : (
            <>
              <svg className={styles.svg} viewBox={`0 0 ${PICTURE.width} ${PICTURE.height}`} aria-hidden="true" focusable="false">
                <Basemap place={layout.place} />
                {coverage ? (
                  <defs>
                    <pattern id={hatch} width="8" height="8" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
                      <line x1="0" y1="0" x2="0" y2="8" stroke="var(--c-ink)" strokeWidth="3" />
                    </pattern>
                  </defs>
                ) : null}
                {visiting.map((option, index) => {
                  const centre = at(offset + fixed.length + index);
                  if (centre === undefined || option.coverage === null) return null;
                  const look = coverage ? areaStyleOf(index) : null;
                  return (
                    <circle
                      key={option.serviceId}
                      cx={centre.x}
                      cy={centre.y}
                      r={radiusPx(option.coverage.radiusKm, layout.pxPerDegree)}
                      fill={look === null ? 'currentColor' : look.color}
                      fillOpacity={look === null ? 0.09 : look.fillOpacity}
                      stroke={look === null ? 'currentColor' : look.color}
                      strokeOpacity={look === null ? 0.5 : 1}
                      strokeWidth={look === null ? 2 : 3}
                      strokeDasharray={look === null ? '6 6' : look.dash}
                      data-el={coverage ? `ADV-MAP-COVER-AREA-${option.serviceId.toUpperCase()}` : undefined}
                    />
                  );
                })}
                {lenses.map((ring, index) => (
                  <path
                    key={index}
                    d={`${ring.map((point, at2) => `${at2 === 0 ? 'M' : 'L'}${layout.place(point).x.toFixed(1)} ${layout.place(point).y.toFixed(1)}`).join('')}Z`}
                    fill={`url(#${hatch})`}
                    fillOpacity={0.55}
                    data-el="ADV-MAP-COVER-OVERLAP"
                  />
                ))}
                {routeEnd === undefined || routeEnd === null ? null : (
                  <line
                    className={styles.route}
                    x1={at(0).x}
                    y1={at(0).y}
                    x2={routeEnd.x}
                    y2={routeEnd.y}
                    stroke="currentColor"
                    strokeWidth={3}
                    strokeDasharray="2 8"
                    strokeLinecap="round"
                    data-el="ADV-MAP-ROUTE"
                  />
                )}
              </svg>
              {patientArea === null ? null : patientEl(pinCss(0))}
              {fixed.map((option, index) => pinEl(option, pinCss(offset + index), false))}
              {visiting.map((option, index) => pinEl(option, pinCss(offset + fixed.length + index), true))}
            </>
          )}
        </div>
        <div className={styles.legend}>
          <p>
            {captionOf({ patient: patientArea !== null, visiting: visiting.length > 0, route: routeEnd !== null && routeEnd !== undefined, coverage, tiles: showTiles })}
          </p>
          <UnplacedNote options={options} />
          {showTiles ? null : <p>{BASEMAP_ATTRIBUTION}</p>}
        </div>
      </div>

      {coverage ? <CoveragePanel options={options} patientArea={patientArea} place={postcode} /> : null}

      {selected === null ? null : (
        <PinCard caseId={caseId} option={selected} onCriteria={onCriteria} onNetworkCriteria={onNetworkCriteria} />
      )}
    </section>
  );
}

function PinCard({
  caseId,
  option,
  onCriteria,
  onNetworkCriteria,
}: {
  caseId: string;
  option: OptionView;
  onCriteria?: (serviceId: string) => void;
  onNetworkCriteria?: (serviceId: string) => void;
}) {
  const [travelOpen, setTravelOpen] = useState(false);
  const free = freeText(option);
  const age = option.dataAgeSeconds === null ? null : `Updated ${durationText(Math.floor(option.dataAgeSeconds / 60))} ago`;
  const network = option.network;
  // The own services always have the details; a network row has them when the travel is drawn in legs (the
  // options list's rows are; the network page's are a range only).
  const hasLegs = network === null || (option.travel?.legs.length ?? 0) > 0;

  return (
    <section className={styles.card} aria-label={option.name} data-el="ADV-MAP-CARD">
      <header className={styles.cardHead}>
        <div>
          <h3 className={styles.name}>{option.name}</h3>
          {network === null ? null : <p className={styles.caption}>{network.organisation}</p>}
        </div>
        <StatusBadge status={option.status} />
      </header>
      {free === null ? null : <p className={styles.line}>{free}</p>}
      <p className={styles.line}>{travelLine(option)}</p>
      {age === null ? null : <p className={styles.line}>{age}</p>}
      {option.criteriaVersion === null ? null : <p className={styles.line}>{`Criteria version ${option.criteriaVersion}`}</p>}
      {network === null ? <ServicePhone phone={option.phone} /> : null}
      {network === null ? <OptionBooking caseId={caseId} option={option} /> : <NetworkServiceLine option={option} className={styles.line} />}
      <div className={styles.actions}>
        {network === null ? (
          <Button variant="secondary" dataEl="ADV-OPT-CRITERIA-BTN" onClick={() => onCriteria?.(option.serviceId)}>
            Criteria
          </Button>
        ) : onNetworkCriteria === undefined ? null : (
          <Button variant="secondary" dataEl="ADV-OPT-CRITERIA-BTN" onClick={() => onNetworkCriteria(option.serviceId)}>
            Criteria
          </Button>
        )}
        {hasLegs ? (
          <Button variant="secondary" dataEl="ADV-MAP-TRAVEL-BTN" onClick={() => setTravelOpen((open) => !open)}>
            Travel details
          </Button>
        ) : null}
      </div>
      {travelOpen ? <TravelDetails option={option} caseId={caseId} /> : null}
    </section>
  );
}
