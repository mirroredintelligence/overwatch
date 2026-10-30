'use client';

import { useEffect, useState } from 'react';
import { Button } from '@/components/ui/Button';
import { Chip } from '@/components/ui/Chip';
import { FlowsTable } from './FlowsTable';
import { HeatGrid } from './HeatGrid';
import styles from '../console/Console.module.css';
import { NEEDS, PERIODS, type Count, type Declined, type Need, type Period, type Planning } from '@/lib/planning/types';

// The planning view (W51): where capacity ran out, and where patients went instead, from the
// decision log. Counts are referrals and acceptances, never a person or an advisor.

/** A headline count in words: the number, or "Fewer than 10" when the back end withheld it. */
function countText(figure: Count): string {
  return figure.suppressed || figure.count === null ? 'Fewer than 10' : String(figure.count);
}

export function PlanningView() {
  const [period, setPeriod] = useState<Period>('90d');
  const [need, setNeed] = useState<Need>('all');
  const [result, setResult] = useState<{ key: string; data: Planning | null; error: string | null } | null>(null);
  const key = `${period}|${need}`;

  useEffect(() => {
    let cancelled = false;
    const params = new URLSearchParams({ period, need });
    fetch(`/api/bff/planning?${params.toString()}`, { credentials: 'same-origin' })
      .then(async (response) => {
        if (!response.ok) throw new Error('status');
        return (await response.json()) as Planning;
      })
      .then((data) => {
        if (!cancelled) setResult({ key, data, error: null });
      })
      .catch(() => {
        if (!cancelled) setResult({ key, data: null, error: 'The planning view could not be loaded. Try again.' });
      });
    return () => {
      cancelled = true;
    };
  }, [period, need, key]);

  const current = result?.key === key ? result : null;
  const data = current?.data ?? null;
  const exportHref = `/api/bff/planning/export?${new URLSearchParams({ period, need }).toString()}`;

  return (
    <div className={styles.page}>
      <p className={styles.help}>Managers and ICB · sign in with your staff account</p>
      <h1 className={styles.heading}>Right-sizing: where capacity ran out</h1>

      <div className={styles.chips} role="group" aria-label="Period">
        {PERIODS.map((item) => (
          <Chip key={item.value} pressed={period === item.value} onPressedChange={() => setPeriod(item.value)} dataEl={`PLAN-PERIOD-${item.value.toUpperCase()}`}>
            {item.label}
          </Chip>
        ))}
      </div>
      <div className={styles.chips} role="group" aria-label="Need group">
        {NEEDS.map((item) => (
          <Chip key={item.value} pressed={need === item.value} onPressedChange={() => setNeed(item.value)} dataEl={`PLAN-NEED-${item.value.toUpperCase()}`}>
            {item.label}
          </Chip>
        ))}
      </div>

      {current?.error && <p role="alert" className={styles.alert}>{current.error}</p>}
      {!current && <p className={styles.help}>Loading</p>}

      {data !== null && (
        <>
          <p>{data.cohort}</p>
          <details>
            <summary data-el="PLAN-COHORT-BTN">Show cohort definition</summary>
            <p className={styles.help}>
              Period: {PERIODS.find((item) => item.value === period)?.label}. Need group: {NEEDS.find((item) => item.value === need)?.label}.
              Groups under 10 are hidden.
            </p>
          </details>

          <section aria-labelledby="headline-heading" className={styles.section}>
            <h2 id="headline-heading" className={styles.heading}>Headline</h2>
            <p className={styles.heading}>{`${countText(data.referrals)} referrals`}</p>
            <p>
              {data.bestFitUnavailable.pct === null || data.bestFitUnavailable.suppressed
                ? `${countText(data.bestFitUnavailable)} best fit unavailable (Full, closed or not updated.)`
                : `${countText(data.bestFitUnavailable)} best fit unavailable (${data.bestFitUnavailable.pct}% of referrals. Full, closed or not updated.)`}
            </p>
            <p>{`${countText(data.wentElsewhere)} went to another suitable service`}</p>
          </section>

          <FlowsTable flows={data.flows} total={data.bestFitUnavailable.count} />
          <HeatGrid grid={data.grid} busiest={data.busiest} />

          <section aria-labelledby="declined-heading" className={styles.section}>
            <h2 id="declined-heading" className={styles.heading}>Declined despite showing capacity</h2>
            <p className={styles.help}>For a conversation with each service. Not a league table and not used to assess advisors.</p>
            <table className={styles.table} aria-label="Declined despite showing capacity table">
              <thead>
                <tr>
                  <th scope="col">Service</th>
                  <th scope="col">Referrals</th>
                </tr>
              </thead>
              <tbody>
                {data.declinedDespite.map((row: Declined) => (
                  <tr key={row.service}>
                    <td>{row.service}</td>
                    <td>{row.suppressed || row.count === null ? 'fewer than 10' : row.count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>

          <section aria-labelledby="reading-heading" className={styles.section}>
            <h2 id="reading-heading" className={styles.heading}>How to read this</h2>
            <p>
              These are referral and acceptance counts from the coordination team decision log. They do not show what happened to patients
              afterwards. Outcomes need linked data and come in phase 2.
            </p>
          </section>

          <Button variant="neutral" href={exportHref} dataEl="PLAN-EXPORT-BTN">
            Export table (CSV)
          </Button>
        </>
      )}
    </div>
  );
}
