'use client';

import { useState } from 'react';
import { Button } from '@/components/ui/Button';
import { Banner } from '@/components/ui/Banner';
import { Disclose } from '@/components/admin/Disclose';
import { type AlertPreferences } from '@/lib/exec/alertPrefs';
import { DEPUTY_REQUIRED, hasDeputy, SAVE_FAILED, savePreferences } from '@/lib/exec/savePreferences';
import { formatCount, formatMinutesFigure, formatPct } from '@/lib/exec/weekFormat';
import { timeBack, type WeekSummary as Summary } from '@/lib/exec/weekSummary';
import styles from './WeekSummary.module.css';

// This week (W41, ExecApp1 screen 3; PWeek). Four figures in words, the time back as a labelled estimate with
// its sum behind a disclosure, the footnote on small groups, and the Monday switch: the same preference the
// alert settings hold (W39). The pressure chart is not in this release: the week summary has no per-day series.

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
  const [sumOpen, setSumOpen] = useState(false);
  const time = timeBack(summary.updates, summary.minutesPerCall);

  // While the minutes per call are unset, the estimate names its placeholder and says it is not measured yet.
  const count = summary.updates.suppressed ? null : summary.updates.value;
  const unmeasured = summary.minutesPerCall === null;
  const sentence =
    summary.timeBackText ??
    (count !== null && unmeasured
      ? `${count} updates by text, app or email. Each replaces about one phone call of [x] minutes.`
      : time.sentence);
  const showNote = unmeasured && summary.timeBackText === null && count !== null;
  const sum = count === null || summary.timeBackText !== null ? null : unmeasured ? `${count} × [x] minutes` : time.estimate;

  const figures = [
    { value: formatCount(summary.referrals), label: 'referrals', note: 'Last complete week' },
    { value: formatPct(summary.bestFitUnavailablePct), label: 'best fit not available', note: 'Full, closed or not updated' },
    { value: formatPct(summary.onTimePct), label: 'capacity updates on time', note: 'Updates by the due time' },
    { value: formatMinutesFigure(summary.medianMinutesToConfirmed), label: 'median to a confirmed booking', note: 'Request sent to confirmed' },
  ];

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
    <div className={styles.page}>
      <header className={styles.header}>
        <p className={styles.range}>{rangeText(summary.from, summary.to)}</p>
        <h1 className={styles.title}>This week</h1>
      </header>

      <div className={styles.body}>
        <div className={styles.figures}>
          <ul className={styles.tiles} aria-label="Figures for the week">
            {figures.map((figure) => (
              <li key={figure.label} className={styles.tile}>
                <span className={styles.tileValue}>{figure.value}</span>
                <span className={styles.tileLabel}>{figure.label}</span>
                <span className={styles.tileNote}>{figure.note}</span>
              </li>
            ))}
          </ul>
        </div>

        <div className={styles.side}>
          <section className={styles.card} aria-labelledby="week-time-back">
            <h2 id="week-time-back" className={styles.eyebrow}>Time back (estimate)</h2>
            <p className={styles.sentence}>{sentence}</p>
            {showNote ? <p className={styles.note}>An estimate until we measure the baseline.</p> : null}
            {sum !== null ? (
              <Disclose open={sumOpen} onToggle={() => setSumOpen(!sumOpen)} title="Show the sum">
                <p className={styles.sum}>{sum}</p>
              </Disclose>
            ) : null}
          </section>

          <section className={styles.card} aria-labelledby="week-monday">
            <h2 id="week-monday" className={styles.eyebrow}>Every Monday</h2>
            <p className={styles.sentence}>Get this summary by email, so there is one less meeting to hold.</p>
            {prefs !== null ? (
              <div className={styles.actions}>
                <Button variant="secondary" busy={busy} onClick={toggleMonday} dataEl="EXEC-WEEK-MONDAY-BTN">
                  {on ? 'You will get this each Monday.' : 'Send me this each Monday'}
                </Button>
              </div>
            ) : null}
            {error ? <Banner tone="warning" title={error} /> : null}
          </section>

          <p className={styles.footer}>Counts under 10 are hidden. Outcomes are not shown yet. No patient information on this screen.</p>
        </div>
      </div>
    </div>
  );
}
