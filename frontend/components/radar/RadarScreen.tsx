'use client';

import { ShapeIcon, STATUS_LABELS, STATUS_SHAPES } from '@/components/ui/StatusBadge';
import type { OptionView } from '@/lib/advisor/options';
import { coverSummary, coveringPatient, visitingOf } from '@/lib/radar/radar';
import { useMapPreload } from '@/components/map/TileMap';
import { RadarFrame } from './RadarFrame';
import { areaStyleOf, RadarMap } from './RadarMap';
import styles from './radar.module.css';

// Radar: who covers this area (RadarWeb 1, from the Radar board). Visiting services are areas, the overlap
// of two is hatched, and the places to go are icons. The patient is at the postcode centre. The picture sits
// beside a key and the list of who covers the district. Drive-time rings and traffic are in the design but
// have no data behind them yet: the key says they are off, and why, rather than drawing them from nothing.

/** "Accepting · 4", "Over capacity · +2": the status word, then the figure when the service sent one. */
function statusLine(option: OptionView): string {
  const word = STATUS_LABELS[option.status];
  if (option.status === 'over-capacity' && option.overBy !== null) return `${word} · +${option.overBy}`;
  return option.effectiveAvailable === null ? word : `${word} · ${option.effectiveAvailable}`;
}

export function RadarScreen({ caseId }: { caseId: string }) {
  useMapPreload();
  return (
    <RadarFrame caseId={caseId} current="radar">
      {({ parts, place, toggle }) => {
        const covering = coveringPatient(parts.options, parts.patientArea);
        const visiting = visitingOf(parts.options);
        const unplaced = parts.options.filter((option) => option.position === null && option.coverage === null).length;
        return (
          <section className={styles.screen} aria-label="Radar">
            <h2 className={styles.srOnly}>{`Who covers ${place}`}</h2>
            <div className={styles.toggleRow}>
              {toggle}
              <span className={styles.hint}>{`Who covers ${place} · the patient is shown at the postcode centre`}</span>
            </div>

            <div className={styles.radar}>
              <div className={styles.mapCard}>
                <RadarMap options={parts.options} patientArea={parts.patientArea} postcode={place} />
                {unplaced === 0 ? null : (
                  <p className={styles.note}>{`${unplaced} ${unplaced === 1 ? 'service has' : 'services have'} no place on the picture. The list has every service.`}</p>
                )}
              </div>

              <section className={styles.side} aria-label="Key and services">
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
                    <li className={`${styles.keyRow} ${styles.keyOff}`}>
                      <span className={`${styles.swatch} ${styles.swatchOff}`} aria-hidden="true" />
                      Drive-time rings: off, no data yet
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
                    {coverSummary(covering)}
                  </p>
                  <p className={styles.note}>Places to go are icons on the picture, or on the list, not areas.</p>
                </div>
              </section>
            </div>
          </section>
        );
      }}
    </RadarFrame>
  );
}

function AreaSwatch({ color, dashed }: { color: string; dashed: boolean }) {
  return (
    <svg className={styles.swatchSvg} width="22" height="22" viewBox="0 0 22 22" aria-hidden="true" focusable="false">
      <rect x="2" y="2" width="18" height="18" rx="5" fill={color} fillOpacity={0.2} stroke={color} strokeWidth={3} strokeDasharray={dashed ? '5 3' : undefined} />
    </svg>
  );
}
