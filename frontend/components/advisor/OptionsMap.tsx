'use client';

import { useState } from 'react';
import { Button } from '@/components/ui/Button';
import { StatusBadge } from '@/components/ui/StatusBadge';
import type { LatLon } from '@/lib/map/project';
import { layoutOf, PICTURE, percentOf, radiusPx } from '@/lib/map/layout';
import { type OptionView } from '@/lib/advisor/options';
import { durationText } from '@/lib/board/format';
import { TravelDetails } from './TravelDetails';
import styles from './map.module.css';

// The options drawn as a schematic (W50): the patient's area at the postcode centre, each fixed site as a
// labelled pin, and each visiting service as a dashed area. It is not a tile map: no tile provider is
// chosen and no third-party script is loaded. The list holds every service the map shows.

const CAPTION = 'Patient shown at postcode centre. Dashed areas are where a visiting service can attend.';
const PATIENT_RADIUS = 9;

export type OptionsMapProps = {
  caseId: string;
  postcode: string;
  patientArea: LatLon | null;
  options: OptionView[];
  selectedId: string | null;
  onSelect: (serviceId: string) => void;
  onRequest?: (serviceId: string) => void;
  onCriteria?: (serviceId: string) => void;
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

export function OptionsMap({
  caseId,
  postcode,
  patientArea,
  options,
  selectedId,
  onSelect,
  onRequest,
  onCriteria,
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

  return (
    <section className={styles.screen} aria-label={`Map of options near ${postcode}`}>
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
                fill="none"
                stroke="currentColor"
                strokeWidth={2}
                strokeDasharray="6 6"
              />
            );
          })}
          {patientArea === null ? null : (
            <circle cx={at(0).x} cy={at(0).y} r={PATIENT_RADIUS} fill="currentColor" />
          )}
        </svg>

        {patientArea === null ? null : (
          <span className={styles.visiting} style={percentOf(at(0))}>
            Patient area
          </span>
        )}
        {fixed.map((option, index) => (
          <button
            key={option.serviceId}
            type="button"
            className={styles.pin}
            style={percentOf(at(offset + index))}
            aria-label={option.name}
            aria-pressed={option.serviceId === selectedId}
            data-el={`ADV-MAP-PIN-${option.serviceId.toUpperCase()}`}
            onClick={() => onSelect(option.serviceId)}
          >
            {option.name}
          </button>
        ))}
        {visiting.map((option, index) => (
          <span key={option.serviceId} className={styles.visiting} style={percentOf(at(offset + fixed.length + index))}>
            {`${option.name} (visiting)`}
          </span>
        ))}
      </div>
      <p className={styles.caption}>{CAPTION}</p>

      {selected === null ? null : (
        <PinCard caseId={caseId} option={selected} onRequest={onRequest} onCriteria={onCriteria} />
      )}
    </section>
  );
}

function PinCard({
  caseId,
  option,
  onRequest,
  onCriteria,
}: {
  caseId: string;
  option: OptionView;
  onRequest?: (serviceId: string) => void;
  onCriteria?: (serviceId: string) => void;
}) {
  const [travelOpen, setTravelOpen] = useState(false);
  const free = freeText(option);
  const age = option.dataAgeSeconds === null ? null : `Updated ${durationText(Math.floor(option.dataAgeSeconds / 60))} ago`;
  const network = option.network;

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
      <div className={styles.actions}>
        {network === null ? (
          <Button variant="primary" dataEl="ADV-OPT-REQUEST-BTN" onClick={() => onRequest?.(option.serviceId)}>
            Request booking
          </Button>
        ) : null}
        <Button variant="secondary" dataEl="ADV-OPT-CRITERIA-BTN" onClick={() => onCriteria?.(option.serviceId)}>
          Criteria
        </Button>
        <Button variant="secondary" dataEl="ADV-MAP-TRAVEL-BTN" onClick={() => setTravelOpen((open) => !open)}>
          Travel details
        </Button>
      </div>
      {travelOpen ? <TravelDetails option={option} caseId={caseId} /> : null}
    </section>
  );
}
