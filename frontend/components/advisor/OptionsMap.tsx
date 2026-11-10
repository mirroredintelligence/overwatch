'use client';

import { useState } from 'react';
import { Button } from '@/components/ui/Button';
import { ShapeIcon, STATUS_SHAPES, StatusBadge } from '@/components/ui/StatusBadge';
import type { LatLon } from '@/lib/map/project';
import { layoutOf, PICTURE, percentOf, radiusPx } from '@/lib/map/layout';
import { type OptionView } from '@/lib/advisor/options';
import { durationText } from '@/lib/board/format';
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

const CAPTION =
  'Patient shown at postcode centre. Dashed areas are where a visiting service can attend. The dotted line is the route to the selected site.';

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
}: OptionsMapProps) {
  const fixed = options.filter((option) => option.position !== null);
  const visiting = options.filter((option) => option.coverage !== null);
  const points = [
    ...(patientArea === null ? [] : [patientArea]),
    ...fixed.map((option) => option.position as LatLon),
    ...visiting.map((option) => option.coverage as LatLon),
  ];
  const layout = layoutOf(points);
  const at = (index: number) => layout.points[index];
  const offset = patientArea === null ? 0 : 1;
  const selected = options.find((option) => option.serviceId === selectedId) ?? null;
  // The route to the selected fixed site: a dotted line from the patient (W50, MapWeb). A visiting service
  // comes to the patient, so it has no route to draw.
  const selectedIndex = selected === null ? -1 : fixed.findIndex((option) => option.serviceId === selected.serviceId);
  const routeEnd = selectedIndex < 0 || patientArea === null ? null : at(offset + selectedIndex);

  return (
    <section className={styles.mapWrap} aria-label={`Map of options near ${postcode}`}>
      <div className={styles.mapCard}>
        <div className={styles.picture}>
          <svg className={styles.svg} viewBox={`0 0 ${PICTURE.width} ${PICTURE.height}`} aria-hidden="true" focusable="false">
            {visiting.map((option, index) => {
              const centre = at(offset + fixed.length + index);
              if (centre === undefined || option.coverage === null) return null;
              return (
                <circle
                  key={option.serviceId}
                  cx={centre.x}
                  cy={centre.y}
                  r={radiusPx(option.coverage.radiusKm, layout.pxPerDegree)}
                  fill="currentColor"
                  fillOpacity={0.09}
                  stroke="currentColor"
                  strokeOpacity={0.5}
                  strokeWidth={2}
                  strokeDasharray="6 6"
                />
              );
            })}
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

          {patientArea === null ? null : (
            <StyledSpan className={styles.patient} css={percentOf(at(0))}>
              <span className={styles.patientDot} aria-hidden="true" />
              <span className={styles.patientLabel}>Patient area</span>
            </StyledSpan>
          )}
          {fixed.map((option, index) => (
            <StyledButton
              key={option.serviceId}
              type="button"
              className={styles.pin}
              css={percentOf(at(offset + index))}
              aria-label={option.name}
              aria-pressed={option.serviceId === selectedId}
              data-status={option.status}
              data-el={`ADV-MAP-PIN-${option.serviceId.toUpperCase()}`}
              onClick={() => onSelect(option.serviceId)}
            >
              <span className={styles.marker} aria-hidden="true">
                <ShapeIcon shape={STATUS_SHAPES[option.status]} />
              </span>
              <span className={styles.label}>{pinText(option.name, option)}</span>
            </StyledButton>
          ))}
          {visiting.map((option, index) => (
            <StyledButton
              key={option.serviceId}
              type="button"
              className={styles.pin}
              css={percentOf(at(offset + fixed.length + index))}
              aria-label={`${option.name} (visits)`}
              aria-pressed={option.serviceId === selectedId}
              data-status={option.status}
              data-el={`ADV-MAP-AREA-${option.serviceId.toUpperCase()}`}
              onClick={() => onSelect(option.serviceId)}
            >
              <span className={styles.marker} aria-hidden="true">
                <ShapeIcon shape={STATUS_SHAPES[option.status]} />
              </span>
              <span className={styles.label}>{pinText(`${option.name} (visits)`, option)}</span>
            </StyledButton>
          ))}
        </div>
        <div className={styles.legend}>
          <p>{CAPTION}</p>
          <UnplacedNote options={options} />
          <p>
            Drive-time rings and traffic are <strong>off</strong>: there is no data behind them yet.
          </p>
        </div>
      </div>

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
