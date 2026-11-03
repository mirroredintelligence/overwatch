'use client';

import { type ReactNode, useState } from 'react';
import { CaseSummaryLine } from '@/components/advisor/CaseSummaryLine';
import { OptionBooking } from '@/components/advisor/OptionBooking';
import { Button } from '@/components/ui/Button';
import { StatusBadge } from '@/components/ui/StatusBadge';
import type { OptionView } from '@/lib/advisor/options';
import { ageText, freeText, NOT_AVAILABLE, reachText } from '@/lib/radar/compare';
import { comparable } from '@/lib/radar/radar';
import { RadarFrame } from './RadarFrame';
import styles from './radar.module.css';

// Compare the covering services (RadarWeb 2, from the Compare board). It lines up what each option costs and
// does not pick one: there is no score, no rank and no "best" mark, and the order is the one the back end sent
// (the list's order). A request from here is the same request as on the map and the list (W20): only a
// request, until the service confirms. Every column has the same outlined request, so none looks
// recommended. The table turns into a stack on a phone: each measure names the service beside each figure.

const NOTE =
  'This lines up what each option costs. It does not pick one: there is no score, no rank and no best mark. The advisor and the clinical need decide. A request is only a request, and is not booked until the service confirms. Rows that need a service’s round say Not available, which is not zero.';
const WHY: readonly string[] = [
  'Free and status are as the service last reported them. The data age row says how old that is.',
  'Time to reach the patient is a range for the area, not the door: the patient is placed at the postcode centre.',
  'What a visit adds to a round, and which patients are already near, need each service’s round. Overwatch does not hold that yet, so those rows say Not available. It is not zero.',
];

type Row = { id: string; label: string; cell: (option: OptionView) => ReactNode };

function notAvailable() {
  return <span className={styles.na}>{NOT_AVAILABLE}</span>;
}

const ROWS: readonly Row[] = [
  { id: 'criteria', label: 'Meets the criteria', cell: () => 'Yes' },
  { id: 'status', label: 'Status now', cell: (option) => <StatusBadge status={option.status} /> },
  { id: 'free', label: 'Free', cell: freeText },
  { id: 'reach', label: 'Time to reach the patient', cell: reachText },
  { id: 'round', label: 'Adds to today’s round', cell: notAvailable },
  { id: 'near', label: 'Patients already near', cell: notAvailable },
  {
    id: 'age',
    label: 'Data age',
    cell: (option) => (option.staleWarning ? <strong className={styles.old}>{ageText(option)}</strong> : ageText(option)),
  },
];

export function CompareScreen({ caseId }: { caseId: string }) {
  const [why, setWhy] = useState(false);
  const base = `/advisor/case/${encodeURIComponent(caseId)}`;

  return (
    <RadarFrame caseId={caseId} current="compare">
      {({ parts, place, view, toggle }) => {
        const services = comparable(parts.options);
        return (
          <section className={styles.screen} aria-label="Compare">
            <h2 className={styles.srOnly}>Compare for this patient</h2>
            <div className={styles.compareLayout}>
              {view === null ? null : (
                <div className={styles.patient}>
                  <CaseSummaryLine caseId={caseId} ageBand={view.ageBand} postcode={view.postcode} needs={view.needs} urgency={view.urgency} />
                </div>
              )}
              <div className={styles.stage}>
                <div className={styles.toggleRow}>
                  {toggle}
                  <span className={styles.hint}>{`${services.length} ${services.length === 1 ? 'service meets' : 'services meet'} the criteria · same order as the list`}</span>
                </div>

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
                  <div className={styles.tableCard}>
                    <table className={styles.compare} data-el="RADAR-COMPARE">
                      <caption className={styles.srOnly}>The covering services side by side, in the order of the list.</caption>
                      <thead>
                        <tr>
                          <th scope="col">
                            <span className={styles.srOnly}>Measure</span>
                          </th>
                          {services.map((option) => (
                            <th key={option.serviceId} scope="col">
                              <span className={styles.colName}>{option.name}</span>
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
                          <th scope="row">
                            <span className={styles.srOnly}>Request</span>
                          </th>
                          {services.map((option) => (
                            <td key={option.serviceId} data-label={option.name} data-request="outlined" className={styles.requestCell}>
                              <div role="group" aria-label={`Request ${option.name}`}>
                                <OptionBooking caseId={caseId} option={option} />
                              </div>
                            </td>
                          ))}
                        </tr>
                      </tbody>
                    </table>
                  </div>
                )}

                <p className={styles.shadow} data-el="RADAR-SHADOW">
                  {NOTE}
                </p>
                <div className={styles.actions}>
                  <Button variant="secondary" onClick={() => setWhy((open) => !open)} dataEl="RADAR-WHY-BTN">
                    Why these numbers
                  </Button>
                </div>
                {why ? (
                  <ul className={styles.why} aria-label="Why these numbers" data-el="RADAR-WHY">
                    {WHY.map((line) => (
                      <li key={line}>{line}</li>
                    ))}
                  </ul>
                ) : null}
              </div>
            </div>
          </section>
        );
      }}
    </RadarFrame>
  );
}
