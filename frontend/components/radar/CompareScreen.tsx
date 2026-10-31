'use client';

import { type ReactNode, useState } from 'react';
import { OptionBooking } from '@/components/advisor/OptionBooking';
import { Banner } from '@/components/ui/Banner';
import { Button } from '@/components/ui/Button';
import { StatusBadge } from '@/components/ui/StatusBadge';
import type { OptionView } from '@/lib/advisor/options';
import { ageText, freeText, NOT_AVAILABLE, reachText } from '@/lib/radar/compare';
import { comparable } from '@/lib/radar/radar';
import { RadarFrame } from './RadarFrame';
import styles from './radar.module.css';

// Compare the covering services (RadarWeb 2). It lines up what each option costs and does not pick one:
// there is no score, no rank and no "best" mark, and the order is the one the back end sent. A request
// from here is the same request as on the map and the list (W20): only a request, until the service
// confirms. The table turns into a stack on a phone: each measure names the service beside each figure.

const SHADOW =
  'This lines up what each option costs. It does not pick one. The advisor and the clinical need decide.';
const REQUEST_NOTE = 'A request is only a request. It is not booked until the service confirms.';
const WHY: readonly string[] = [
  'Free and status are as the service last reported them. The data age row says how old that is.',
  'Time to reach the patient is a range for the area, not the door: the patient is placed at the postcode centre.',
  'What a visit adds to a round, and which patients are already near, need each service’s round. Overwatch does not hold that yet, so those rows say Not available. It is not zero.',
];

type Row = { id: string; label: string; cell: (option: OptionView) => ReactNode };

const ROWS: readonly Row[] = [
  { id: 'criteria', label: 'Meets the criteria', cell: () => 'Yes' },
  { id: 'status', label: 'Status now', cell: (option) => <StatusBadge status={option.status} /> },
  { id: 'free', label: 'Free', cell: freeText },
  { id: 'reach', label: 'Time to reach the patient', cell: reachText },
  { id: 'round', label: 'Adds to today’s round', cell: () => NOT_AVAILABLE },
  { id: 'near', label: 'Patients already near', cell: () => NOT_AVAILABLE },
  { id: 'age', label: 'Data age', cell: ageText },
];

export function CompareScreen({ caseId }: { caseId: string }) {
  const [why, setWhy] = useState(false);
  const base = `/advisor/case/${encodeURIComponent(caseId)}`;

  return (
    <RadarFrame caseId={caseId} current="compare">
      {({ parts, place }) => {
        const services = comparable(parts.options);
        return (
          <section className={styles.screen} aria-label="Compare">
            <h2 className={styles.heading}>Compare for this patient</h2>
            <Banner tone="info" title="Shadow mode" dataEl="RADAR-SHADOW">
              {SHADOW}
            </Banner>

            {services.length === 0 ? (
              <>
                <p role="status">{`No service visits or works remotely for ${place}, so there is nothing to compare here. The three ways view lists the places to go.`}</p>
                <div className={styles.actions}>
                  <Button variant="primary" href={`${base}/ways`}>
                    Three ways to meet the need
                  </Button>
                </div>
              </>
            ) : (
              <>
                <table className={styles.compare} data-el="RADAR-COMPARE">
                  <caption className={styles.srOnly}>The covering services side by side. Not ranked.</caption>
                  <thead>
                    <tr>
                      <th scope="col">Measure</th>
                      {services.map((option) => (
                        <th key={option.serviceId} scope="col">
                          {option.name}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {ROWS.map((row) => (
                      <tr key={row.id} data-row={row.id}>
                        <th scope="row">{row.label}</th>
                        {services.map((option) => (
                          <td key={option.serviceId} data-label={option.name}>
                            {row.cell(option)}
                          </td>
                        ))}
                      </tr>
                    ))}
                    <tr data-row="request">
                      <th scope="row">Request</th>
                      {services.map((option) => (
                        <td key={option.serviceId} data-label={option.name}>
                          <div role="group" aria-label={`Request ${option.name}`}>
                            <OptionBooking caseId={caseId} option={option} />
                          </div>
                        </td>
                      ))}
                    </tr>
                  </tbody>
                </table>
                <p className={styles.note}>{REQUEST_NOTE}</p>
              </>
            )}

            <div className={styles.actions}>
              <Button variant="secondary" onClick={() => setWhy((open) => !open)} dataEl="RADAR-WHY-BTN">
                Why these numbers
              </Button>
              <Button variant="neutral" href={`${base}/radar`}>
                Back to the radar
              </Button>
            </div>
            {why ? (
              <ul className={styles.why} aria-label="Why these numbers" data-el="RADAR-WHY">
                {WHY.map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ul>
            ) : null}
          </section>
        );
      }}
    </RadarFrame>
  );
}
