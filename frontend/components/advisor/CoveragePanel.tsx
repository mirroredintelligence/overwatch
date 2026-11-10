import { ShapeIcon, STATUS_LABELS, STATUS_SHAPES } from '@/components/ui/StatusBadge';
import type { OptionView } from '@/lib/advisor/options';
import { areaStyleOf } from '@/lib/map/areaStyle';
import type { LatLon } from '@/lib/map/project';
import { coverSummary, coveringPatient, visitingOf } from '@/lib/radar/radar';
import styles from '../radar/radar.module.css';

// What the "Who covers this area" layer adds beside the map (DEC-1372): the key to the outlined areas, and the
// services whose area includes the patient's area, with the one-line summary. It was the Radar's side panel.

function statusLine(option: OptionView): string {
  const word = STATUS_LABELS[option.status];
  if (option.status === 'over-capacity' && option.overBy !== null) return `${word} · +${option.overBy}`;
  return option.effectiveAvailable === null ? word : `${word} · ${option.effectiveAvailable}`;
}

function AreaSwatch({ color, dashed }: { color: string; dashed: boolean }) {
  return (
    <svg className={styles.swatchSvg} width="22" height="22" viewBox="0 0 22 22" aria-hidden="true" focusable="false">
      <rect x="2" y="2" width="18" height="18" rx="5" fill={color} fillOpacity={0.2} stroke={color} strokeWidth={3} strokeDasharray={dashed ? '5 3' : undefined} />
    </svg>
  );
}

export function CoveragePanel({ options, patientArea, place }: { options: OptionView[]; patientArea: LatLon | null; place: string }) {
  const visiting = visitingOf(options);
  const covering = coveringPatient(options, patientArea);
  return (
    <section className={styles.side} aria-label="Key and services" data-el="ADV-MAP-COVERAGE">
      <div className={styles.card}>
        <h3 className={styles.kicker}>Key</h3>
        <ul className={styles.key}>
          {visiting.map((option, index) => {
            const look = areaStyleOf(index);
            return (
              <li key={option.serviceId} className={styles.keyRow}>
                <AreaSwatch color={look.color} dashed={look.dash !== undefined} />
                {`${option.name} visits this area`}
              </li>
            );
          })}
          <li className={styles.keyRow}>
            <span className={`${styles.swatch} ${styles.swatchHatch}`} aria-hidden="true" />
            Both visit: hatched
          </li>
          <li className={styles.keyRow}>
            <span className={`${styles.swatch} ${styles.swatchPlace}`} aria-hidden="true" />
            A place to go to
          </li>
        </ul>
      </div>

      <div className={styles.card} data-el="RADAR-COVERING">
        <h3 className={styles.kicker}>{`Covering ${place}`}</h3>
        {covering.length === 0 ? null : (
          <ul className={styles.coverList}>
            {covering.map((option) => (
              <li key={option.serviceId} className={styles.coverRow}>
                <strong>{option.name}</strong>
                <span className={styles.coverStatus}>
                  <ShapeIcon shape={STATUS_SHAPES[option.status]} />
                  <span>{statusLine(option)}</span>
                </span>
              </li>
            ))}
          </ul>
        )}
        <p className={styles.summary} role="status" data-el="RADAR-SUMMARY">
          {coverSummary(covering, patientArea !== null)}
        </p>
        <p className={styles.note}>Places to go are pins on the map, or on the list, not areas.</p>
      </div>
    </section>
  );
}
