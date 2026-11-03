'use client';

import { useEffect, useState } from 'react';
import { Disclose } from '@/components/admin/Disclose';
import { PageHeader } from '@/components/shell/PageHeader';
import { Button } from '@/components/ui/Button';
import { Chip } from '@/components/ui/Chip';
import { Loading, Skeleton } from '@/components/ui/Skeleton';
import { FlowsTable } from './FlowsTable';
import { HeatGrid } from './HeatGrid';
import layout from './Planning.module.css';
import { NEEDS, PERIODS, type Count, type Declined, type Need, type Period, type Planning } from '@/lib/planning/types';

// The right-sizing page (W51): where capacity ran out, and where patients went instead, from the
// decision log. Counts are referrals and acceptances, never a person or an advisor. A count under 10
// reads "under 10", never zero.

/** A headline count in words: the number, or "Under 10" when the back end withheld it. */
function countText(figure: Count): string {
  return figure.suppressed || figure.count === null ? 'Under 10' : String(figure.count);
}

export function PlanningView() {
  const [period, setPeriod] = useState<Period>('90d');
  const [need, setNeed] = useState<Need>('all');
  const [open, setOpen] = useState<'cohort' | 'reading' | null>(null);
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
  const periodLabel = PERIODS.find((item) => item.value === period)?.label ?? '';
  const needLabel = NEEDS.find((item) => item.value === need)?.label ?? '';

  return (
    <div className={layout.view}>
      <PageHeader title="Where capacity ran out">
        <p className={layout.lede}>Right-sizing, from the decision log. Managers and ICB.</p>
      </PageHeader>

      <div className={layout.filters}>
        <div className={layout.filterGroup} role="group" aria-label="Period">
          <span className={layout.filterLabel} aria-hidden="true">Period</span>
          {PERIODS.map((item) => (
            <Chip key={item.value} pressed={period === item.value} onPressedChange={() => setPeriod(item.value)} dataEl={`PLAN-PERIOD-${item.value.toUpperCase()}`}>
              {item.label}
            </Chip>
          ))}
        </div>
        <div className={layout.filterGroup} role="group" aria-label="Need group">
          <span className={layout.filterLabel} aria-hidden="true">Need</span>
          {NEEDS.map((item) => (
            <Chip key={item.value} pressed={need === item.value} onPressedChange={() => setNeed(item.value)} dataEl={`PLAN-NEED-${item.value.toUpperCase()}`}>
              {item.label}
            </Chip>
          ))}
        </div>
        <div className={layout.export}>
          <Button variant="secondary" href={exportHref} dataEl="PLAN-EXPORT-BTN">
            Export table (CSV)
          </Button>
        </div>
      </div>

      {current?.error && <p role="alert" className={layout.alert}>{current.error}</p>}
      {!current && (
        <Loading label="Loading the planning view.">
          <Skeleton shape="block" width="100%" />
        </Loading>
      )}

      {data !== null && (
        <>
          <ul className={layout.stats} aria-label="Headline figures">
            <li className={layout.stat}>
              <span className={layout.statNumber}>{countText(data.referrals)}</span>
              <span className={layout.statLabel}>referrals</span>
              <span className={layout.note}>{`${periodLabel}, ${needLabel.toLowerCase()}`}</span>
            </li>
            <li className={layout.stat}>
              <span className={layout.statNumber}>{countText(data.bestFitUnavailable)}</span>
              <span className={layout.statLabel}>best fit unavailable</span>
              <span className={layout.note}>
                {data.bestFitUnavailable.pct === null || data.bestFitUnavailable.suppressed
                  ? 'Full, closed or not updated.'
                  : `${data.bestFitUnavailable.pct}% of referrals. Full, closed or not updated.`}
              </span>
            </li>
            <li className={layout.stat}>
              <span className={layout.statNumber}>{countText(data.wentElsewhere)}</span>
              <span className={layout.statLabel}>went to another suitable service</span>
              <span className={layout.note}>The rest: fewer than 10 per destination, or no destination recorded</span>
            </li>
          </ul>

          <div className={layout.columns}>
            <div className={layout.wide}>
              <FlowsTable flows={data.flows} total={data.bestFitUnavailable.count} />
            </div>
            <div className={layout.narrow}>
              <HeatGrid grid={data.grid} busiest={data.busiest} />
              <section aria-labelledby="declined-heading" className={layout.card}>
                <h2 id="declined-heading" className={layout.cardTitle}>
                  {`Declined despite showing capacity, ${periodLabel.toLowerCase()}`}
                </h2>
                <table className={layout.table} aria-label="Declined despite showing capacity table">
                  <thead>
                    <tr>
                      <th scope="col">Service</th>
                      <th scope="col" className={layout.num}>Referrals</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.declinedDespite.map((row: Declined) => {
                      const hidden = row.suppressed || row.count === null;
                      return (
                        <tr key={row.service}>
                          <td>{row.service}</td>
                          <td className={`${layout.num} ${hidden ? layout.small : ''}`}>{hidden ? 'under 10' : row.count}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
                <p className={layout.note}>For a conversation with each service. Not a league table and not used to assess advisors.</p>
              </section>
            </div>
          </div>

          <div className={layout.disclosures}>
            <Disclose open={open === 'cohort'} onToggle={() => setOpen(open === 'cohort' ? null : 'cohort')} title="Show cohort definition">
              <p>{data.cohort}</p>
              <p className={layout.note}>
                Period: {periodLabel}. Need group: {needLabel}. Groups under 10 are hidden.
              </p>
            </Disclose>
            <Disclose open={open === 'reading'} onToggle={() => setOpen(open === 'reading' ? null : 'reading')} title="How to read this">
              <p>
                These are referral and acceptance counts from the coordination team decision log. They do not show what happened to patients
                afterwards. Outcomes need linked data and come in phase 2.
              </p>
              <p>Who acts on these findings: [owner to be agreed].</p>
            </Disclose>
          </div>
        </>
      )}
    </div>
  );
}
