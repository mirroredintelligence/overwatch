'use client';

import { useId, useMemo, useState, type CSSProperties, type ReactElement } from 'react';
import { Basemap, BASEMAP_ATTRIBUTION } from '@/components/advisor/Basemap';
import { TileMap, useMapPreload, useWebgl, type TileArea, type TileMarker } from '@/components/map/TileMap';
import { ShapeIcon, STATUS_LABELS, STATUS_SHAPES } from '@/components/ui/StatusBadge';
import { StyledButton, StyledSpan } from '@/components/ui/Styled';
import type { FoundService, LatLng } from '@/lib/advisor/v2/find';
import { layoutOf, PICTURE, percentOf, radiusPx } from '@/lib/map/layout';
import { areaEdges } from '@/lib/map/geo';
import styles from './MapPane.module.css';

// The map of the found services (AdvisorMap board, DEC-1379): one pin per service that has a site, the patient's
// pin, and the "Who covers this area" layer that draws each visiting service's circle. The zoomable tile map is
// used where the browser can draw it (it brings the zoom controls and the attribution); otherwise the schematic of
// the v1 options map. Choosing a pin only calls `onOpen`. The patient's place is drawn and never stored or sent.

export type MapPaneProps = {
  /** The found services in the order they are listed. */
  services: readonly FoundService[];
  /** The patient's place when the postcode could be located, else null (no patient pin is drawn). */
  patient: LatLng | null;
  /** The pin or row the person chose: the page opens that service. */
  onOpen: (service: FoundService) => void;
};

type Circle = { lat: number; lon: number; radiusKm: number };

type Pin = { service: FoundService; at: LatLng; visits: boolean };


function circleOf(service: FoundService): Circle | null {
  const circle = service.coverage.circle;
  return circle === null ? null : { lat: circle.lat, lon: circle.lon, radiusKm: circle.radiusMeters / 1000 };
}

// A service with a site is pinned there. A visiting service with no site is pinned at the centre of its area.
function pinsOf(services: readonly FoundService[]): Pin[] {
  const pins: Pin[] = [];
  for (const service of services) {
    if (service.position !== null) pins.push({ service, at: service.position, visits: false });
    else {
      const circle = circleOf(service);
      if (circle !== null) pins.push({ service, at: { lat: circle.lat, lon: circle.lon }, visits: true });
    }
  }
  return pins;
}

export function MapPane({ services, patient, onOpen }: MapPaneProps): ReactElement {
  useMapPreload();
  const titleId = useId();
  const [coverage, setCoverage] = useState(true);
  const webgl = useWebgl();
  const [tilesFailed, setTilesFailed] = useState(false);

  const pins = useMemo(() => pinsOf(services), [services]);
  const circles = useMemo(() => services.flatMap((service) => circleOf(service) ?? []), [services]);
  const edges = circles.flatMap((circle) => areaEdges(circle, circle.radiusKm));
  const points: LatLng[] = [...(patient === null ? [] : [patient]), ...pins.map((pin) => pin.at), ...circles];
  const empty = pins.length === 0 && patient === null;
  const showTiles = webgl && !tilesFailed && points.length > 0;
  const layout = layoutOf([...points, ...edges]);
  const spot = (at: LatLng): CSSProperties => percentOf(layout.place(at));

  const tileAreas = useMemo<TileArea[]>(
    () =>
      coverage
        ? services.flatMap((service) => {
            const circle = circleOf(service);
            return circle === null
              ? []
              : [{ id: service.serviceId, centre: circle, radiusKm: circle.radiusKm, color: 'var(--c-primary)', dash: true, fillOpacity: 0.1 }];
          })
        : [],
    [services, coverage],
  );

  const patientEl = (css: CSSProperties) => (
    <StyledSpan className={styles.patient} css={css}>
      <span className={styles.patientDot} aria-hidden="true" />
      <span className={styles.patientLabel}>Patient</span>
    </StyledSpan>
  );
  const pinEl = (pin: Pin, css: CSSProperties) => {
    const name = pin.visits ? `${pin.service.name} (visits)` : pin.service.name;
    return (
      <StyledButton
        key={pin.service.serviceId}
        type="button"
        className={styles.pin}
        css={css}
        aria-label={`${name}, ${STATUS_LABELS[pin.service.status]}`}
        data-status={pin.service.status}
        data-el={`ADV-MAP-PIN-${pin.service.serviceId.toUpperCase()}`}
        onClick={() => onOpen(pin.service)}
      >
        <span className={styles.marker} aria-hidden="true">
          <ShapeIcon shape={STATUS_SHAPES[pin.service.status]} />
        </span>
        <span className={styles.label} aria-hidden="true">
          {name}
        </span>
      </StyledButton>
    );
  };

  const markers: TileMarker[] = [
    ...(patient === null ? [] : [{ id: 'patient', at: patient, anchor: 'bottom' as const, node: patientEl({}) }]),
    ...pins.map((pin) => ({ id: pin.service.serviceId, at: pin.at, anchor: 'bottom' as const, node: pinEl(pin, {}) })),
  ];

  return (
    <section className={styles.pane} aria-labelledby={`${titleId}-title`} data-el="ADV-MAPPANE">
      <header className={styles.head}>
        <h2 id={`${titleId}-title`} className={styles.title}>
          Who covers this area
        </h2>
        {empty ? null : (
          <button type="button" className={styles.toggle} aria-pressed={coverage} data-el="ADV-MAP-LAYER-COVERAGE" onClick={() => setCoverage((on) => !on)}>
            Who covers this area
          </button>
        )}
      </header>
      {empty ? (
        <p className={styles.empty}>No locations are held for these services.</p>
      ) : (
        <div className={styles.picture}>
          {showTiles ? (
            <TileMap fit={[...points, ...edges]} areas={tileAreas} route={null} markers={markers} onFailed={() => setTilesFailed(true)} />
          ) : (
            <>
              <svg className={styles.svg} viewBox={`0 0 ${PICTURE.width} ${PICTURE.height}`} aria-hidden="true" focusable="false">
                <Basemap place={layout.place} />
                {coverage
                  ? circles.map((circle, index) => {
                      const centre = layout.place(circle);
                      return (
                        <circle
                          key={index}
                          className={styles.area}
                          cx={centre.x}
                          cy={centre.y}
                          r={radiusPx(circle.radiusKm, layout.pxPerDegree)}
                          data-el="ADV-MAP-COVER-AREA"
                        />
                      );
                    })
                  : null}
              </svg>
              {patient === null ? null : patientEl(spot(patient))}
              {pins.map((pin) => pinEl(pin, spot(pin.at)))}
            </>
          )}
        </div>
      )}
      <div className={styles.foot}>
        {empty || showTiles ? null : <p className={styles.caption}>{BASEMAP_ATTRIBUTION}</p>}
      </div>
    </section>
  );
}
