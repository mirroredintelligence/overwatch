'use client';

import { useState } from 'react';
import { CaseSummaryLine } from '@/components/advisor/CaseSummaryLine';
import { NotSuitableList } from '@/components/advisor/NotSuitableList';
import { Button } from '@/components/ui/Button';
import { Chip } from '@/components/ui/Chip';
import { StatusBadge } from '@/components/ui/StatusBadge';
import type { OptionView } from '@/lib/advisor/options';
import { CAN_TRAVEL, type CanTravel, groupByLane, LANE_TEXT, laneOrder, type Lane } from '@/lib/radar/radar';
import { reachText } from '@/lib/radar/compare';
import { RadarFrame } from './RadarFrame';
import styles from './radar.module.css';

// Three ways to meet the need (RadarWeb 6, RadarPhone 5): the same services as the list, in three lanes. The
// answer to "Can the patient travel?" changes only which lane is shown first; it never hides a lane or a
// service, and it is optional. A lane with nothing in it says so. Services left out are listed with why.

function Row({ option, lane }: { option: OptionView; lane: Lane }) {
  const detail =
    lane === 'place' && option.effectiveAvailable !== null
      ? `${reachText(option)} by road, ${option.effectiveAvailable} ${(option.unitLabel ?? '').replace(/ free$/, '')}`.trim()
      : reachText(option);
  return (
    <li className={styles.way} data-el="RADAR-WAY-ROW">
      <span className={styles.wayText}>
        <strong>{option.name}</strong>
        <span className={styles.wayDetail}>{detail}</span>
      </span>
      <StatusBadge status={option.status} />
    </li>
  );
}

export function WaysScreen({ caseId }: { caseId: string }) {
  const [canTravel, setCanTravel] = useState<CanTravel | null>(null);
  const base = `/advisor/case/${encodeURIComponent(caseId)}`;

  return (
    <RadarFrame caseId={caseId} current="ways">
      {({ parts, view }) => {
        const lanes = groupByLane(parts.options);
        return (
          <section className={styles.screen} aria-label="Three ways">
            <h2 className={styles.heading}>Meeting this need</h2>
            {view === null ? null : (
              <CaseSummaryLine caseId={caseId} ageBand={view.ageBand} postcode={view.postcode} needs={view.needs} urgency={view.urgency} />
            )}

            <fieldset className={styles.layers}>
              <legend className={styles.legend}>Can the patient travel? (optional)</legend>
              <p className={styles.note}>This changes which lane is shown first.</p>
              <div className={styles.chips}>
                {CAN_TRAVEL.map((choice) => (
                  <Chip
                    key={choice.value}
                    pressed={canTravel === choice.value}
                    onPressedChange={(on) => setCanTravel(on ? choice.value : null)}
                    dataEl={`RADAR-TRAVEL-${choice.value.toUpperCase()}`}
                  >
                    {choice.label}
                  </Chip>
                ))}
              </div>
            </fieldset>

            {laneOrder(canTravel).map((lane) => (
              <section key={lane} className={styles.lane} aria-labelledby={`lane-${lane}`} data-lane={lane}>
                <h3 id={`lane-${lane}`} className={styles.laneTitle}>
                  {LANE_TEXT[lane].title}
                </h3>
                <p className={styles.note}>{LANE_TEXT[lane].hint}</p>
                {lanes[lane].length === 0 ? (
                  <p className={styles.note}>None for this patient.</p>
                ) : (
                  <ul className={styles.ways}>
                    {lanes[lane].map((option) => (
                      <Row key={option.serviceId} option={option} lane={lane} />
                    ))}
                  </ul>
                )}
              </section>
            ))}

            {parts.notSuitable.length === 0 ? null : <NotSuitableList items={parts.notSuitable} />}
            <p className={styles.note}>Not suitable places are listed with why, so the advisor can see what was left out.</p>

            <div className={styles.actions}>
              <Button variant="primary" href={`${base}/compare`} dataEl="RADAR-COMPARE-BTN">
                Compare covering services
              </Button>
              <Button variant="neutral" href={`${base}/options`}>
                Back
              </Button>
            </div>
          </section>
        );
      }}
    </RadarFrame>
  );
}
