'use client';

import { useState } from 'react';
import { CaseSummaryLine } from '@/components/advisor/CaseSummaryLine';
import { NotSuitableList } from '@/components/advisor/NotSuitableList';
import { StatusBadge } from '@/components/ui/StatusBadge';
import type { OptionView } from '@/lib/advisor/options';
import { durationText } from '@/lib/board/format';
import { reachText } from '@/lib/radar/compare';
import { CAN_TRAVEL, type CanTravel, groupByLane, LANE_TEXT, laneOrder, type Lane } from '@/lib/radar/radar';
import { RadarFrame } from './RadarFrame';
import styles from './radar.module.css';

// Three ways to meet the need (RadarWeb 6, RadarPhone 5; the Ways and PWays boards): the same services as the
// list, in three lanes. The answer to "Can the patient travel?" changes only which lane is shown first; it
// never hides a lane or a service, and it is optional. A lane with nothing in it says so. Services left out
// are listed with why.

/** The way in: "Visits about 25 to 35 min", the road time for a place, or the range as sent. */
function reachLine(option: OptionView, lane: Lane): string | null {
  if (option.travelText === null) return null;
  const reach = reachText(option);
  if (lane === 'comes') return `Visits ${reach.charAt(0).toLowerCase()}${reach.slice(1)}`;
  if (lane === 'place') return `${reach} by road`;
  return reach;
}

function Way({ caseId, option, lane }: { caseId: string; option: OptionView; lane: Lane }) {
  const reach = reachLine(option, lane);
  const age = option.dataAgeSeconds === null ? null : durationText(Math.floor(option.dataAgeSeconds / 60));
  const free = option.effectiveAvailable === null && option.overBy === null ? null : freeFigure(option);
  const phone = option.status === 'over-capacity' || option.effectiveAvailable === null;
  return (
    <li className={`${styles.way} ${option.status === 'over-capacity' ? styles.wayOver : ''}`} data-el="RADAR-WAY-ROW">
      <strong className={styles.wayName}>{option.name}</strong>
      <span className={styles.wayDetail}>
        {reach}
        {reach !== null && age !== null ? ' · ' : ''}
        {age === null ? null : option.staleWarning ? <strong className={styles.old}>{`${age} · old`}</strong> : `${age} ago`}
      </span>
      <span className={styles.wayStatus}>
        <StatusBadge status={option.status} />
        {free === null ? null : <span>{free}</span>}
      </span>
      {phone ? <span className={styles.wayPhone}>Phone to confirm before offering.</span> : null}
      <a
        className={styles.open}
        href={`/advisor/case/${encodeURIComponent(caseId)}/options?service=${encodeURIComponent(option.serviceId)}`}
        aria-label={`Open ${option.name}`}
      >
        Open
      </a>
    </li>
  );
}

/** "4 referrals in the next 2 hrs", "5 beds free", "+2 over". */
function freeFigure(option: OptionView): string {
  if (option.status === 'over-capacity' && option.overBy !== null) return `+${option.overBy} over`;
  const unit = (option.unitLabel ?? '').trim();
  return `${option.effectiveAvailable} ${unit}`.trim();
}

export function WaysScreen({ caseId }: { caseId: string }) {
  const [canTravel, setCanTravel] = useState<CanTravel | null>(null);

  return (
    <RadarFrame caseId={caseId} current="ways">
      {({ parts, view, toggle }) => {
        const lanes = groupByLane(parts.options);
        return (
          <section className={styles.screen} aria-label="Three ways">
            <h2 className={styles.srOnly}>Meeting this need</h2>
            {view === null ? null : (
              <div className={styles.phoneOnly}>
                <CaseSummaryLine caseId={caseId} ageBand={view.ageBand} postcode={view.postcode} needs={view.needs} urgency={view.urgency} />
              </div>
            )}

            <div className={styles.toggleRow}>
              {toggle}
              <div className={styles.travel} role="group" aria-label="Can the patient travel? (optional)">
                <span className={styles.travelLabel} aria-hidden="true">
                  Can the patient travel? (optional)
                </span>
                <span className={styles.travelChoices}>
                  {CAN_TRAVEL.map((choice) => (
                    <button
                      key={choice.value}
                      type="button"
                      className={styles.choice}
                      aria-pressed={canTravel === choice.value}
                      onClick={() => setCanTravel(canTravel === choice.value ? null : choice.value)}
                      data-el={`RADAR-TRAVEL-${choice.value.toUpperCase()}`}
                    >
                      {choice.label}
                    </button>
                  ))}
                </span>
              </div>
            </div>
            <p className={styles.note}>This only changes which way is shown first. It never hides a way or a service.</p>

            <div className={styles.lanes}>
              {laneOrder(canTravel).map((lane) => (
                <section key={lane} className={styles.lane} aria-labelledby={`lane-${lane}`} data-lane={lane}>
                  <div className={styles.laneHead}>
                    <h3 id={`lane-${lane}`} className={styles.laneTitle}>
                      {LANE_TEXT[lane].title}
                    </h3>
                    <p className={styles.laneHint}>{LANE_TEXT[lane].hint}</p>
                  </div>
                  {lanes[lane].length === 0 ? (
                    <p className={styles.note}>None for this patient.</p>
                  ) : (
                    <ul className={styles.ways}>
                      {lanes[lane].map((option) => (
                        <Way key={option.serviceId} caseId={caseId} option={option} lane={lane} />
                      ))}
                    </ul>
                  )}
                </section>
              ))}
            </div>

            {parts.notSuitable.length === 0 ? null : <NotSuitableList items={parts.notSuitable} />}
          </section>
        );
      }}
    </RadarFrame>
  );
}
