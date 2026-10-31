'use client';

import { useState } from 'react';
import { Button } from '@/components/ui/Button';
import { Banner } from '@/components/ui/Banner';
import { type AlertPreferences } from '@/lib/exec/alertPrefs';
import { DEPUTY_REQUIRED, hasDeputy, SAVE_FAILED, savePreferences } from '@/lib/exec/savePreferences';
import { formatCount, formatMinutesFigure, formatPct } from '@/lib/exec/weekFormat';
import { timeBack, type WeekSummary as Summary } from '@/lib/exec/weekSummary';
import styles from './Exec.module.css';

// This week (W41, ExecApp1 screen 3). Four figures in words, the time back as a labelled estimate, the
// footnote on small groups, and the Monday switch: the same preference the alert settings hold (W39).

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

function dayOf(iso: string): { day: number; month: string } {
  const [, month, day] = iso.split('-');
  return { day: Number(day), month: MONTHS[Number(month) - 1] ?? '' };
}

/** "19 to 25 Oct", or "28 Oct to 3 Nov" across a month end. */
export function rangeText(from: string, to: string): string {
  const start = dayOf(from);
  const end = dayOf(to);
  return start.month === end.month
    ? `${start.day} to ${end.day} ${end.month}`
    : `${start.day} ${start.month} to ${end.day} ${end.month}`;
}

export function WeekSummary({ summary, prefs }: { summary: Summary; prefs: AlertPreferences | null }) {
  const [on, setOn] = useState(prefs?.weeklySummary ?? false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const time = timeBack(summary.updates, summary.minutesPerCall);

  const toggleMonday = async () => {
    if (prefs === null) return;
    if (!hasDeputy(prefs)) {
      setError(DEPUTY_REQUIRED);
      return;
    }
    setBusy(true);
    setError(null);
    const result = await savePreferences({ ...prefs, weeklySummary: !on });
    setBusy(false);
    if (!result.ok) {
      setError(SAVE_FAILED);
      return;
    }
    setOn(!on);
  };

  return (
    <div className={styles.stack}>
      <h1 className={styles.heading}>This week</h1>
      <p>{rangeText(summary.from, summary.to)}</p>

      <ul className={styles.tiles} aria-label="Figures for the week">
        {[
          { value: formatCount(summary.referrals), label: 'referrals' },
          { value: formatPct(summary.bestFitUnavailablePct), label: 'best fit not available' },
          { value: formatPct(summary.onTimePct), label: 'capacity updates on time' },
          { value: formatMinutesFigure(summary.medianMinutesToConfirmed), label: 'median time to a confirmed booking' },
        ].map((figure) => (
          <li key={figure.label} className={styles.tile}>
            <span className={styles.tileValue}>{figure.value}</span>
            <span>{figure.label}</span>
          </li>
        ))}
      </ul>

      <section className={styles.section} aria-labelledby="week-time-back">
        <h2 id="week-time-back" className={styles.heading}>Time back (estimate)</h2>
        <p>{summary.timeBackText ?? time.sentence}</p>
        {summary.timeBackText === null && time.estimate !== null ? (
          <p>
            <span className={styles.estimateLabel}>Estimate</span>
            {` ${time.estimate}`}
          </p>
        ) : null}
      </section>

      <p className={styles.footer}>Counts under 10 are hidden. Outcomes are not shown yet.</p>

      {prefs !== null ? (
        <div className={styles.actions}>
          <Button variant="secondary" busy={busy} onClick={toggleMonday} dataEl="EXEC-WEEK-MONDAY-BTN">
            {on ? 'You will get this each Monday.' : 'Send me this each Monday'}
          </Button>
        </div>
      ) : null}
      {error ? <Banner tone="warning" title={error} /> : null}
    </div>
  );
}
