import { biggestDrop } from '@/lib/console/funnel';
import type { Funnel } from '@/lib/console/insight';
import styles from '../Console.module.css';

// Funnels (W49): the steps as bars with their percentage as text, the biggest drop named in words,
// and the split by channel. A group under 10 reads "fewer than 10" and has no bar.

const SUPPRESSED = 'fewer than 10';

export function FunnelsTab({ funnel }: { funnel: Funnel | null }) {
  if (funnel === null) return <p className={styles.help}>No funnel data for this range.</p>;
  const drop = biggestDrop(funnel.steps);

  return (
    <section className={styles.section} aria-labelledby="funnel-heading">
      <h2 id="funnel-heading" className={styles.heading}>{funnel.label}</h2>
      <ol aria-label="Funnel steps" className={styles.stand}>
        {funnel.steps.map((step) => (
          <li key={step.name}>
            <span>{step.name}</span>{' '}
            {step.suppressed || step.pct === null ? (
              <span>{SUPPRESSED}</span>
            ) : (
              <>
                <span>{step.pct}%</span>
                <div
                  data-bar
                  aria-hidden="true"
                  style={{ width: `${step.pct}%`, height: '0.75rem', background: 'var(--c-primary)', borderRadius: 'var(--radius-chip)' }}
                />
              </>
            )}
          </li>
        ))}
      </ol>
      {drop !== null && (
        <p>
          Biggest drop: {drop.from} to {drop.to}: {drop.points} points
          {drop.exitElementId !== undefined ? `. Exit element ${drop.exitElementId}` : ''}
          {drop.medianSeconds !== undefined ? `. Median time ${drop.medianSeconds} s` : ''}.
        </p>
      )}
      <table className={styles.table} aria-label="Funnel by channel">
        <thead>
          <tr>
            <th scope="col">Channel</th>
            <th scope="col">Share</th>
          </tr>
        </thead>
        <tbody>
          {funnel.split.map((row) => (
            <tr key={row.channel}>
              <td>{row.channel}</td>
              <td>{row.suppressed || row.pct === null ? SUPPRESSED : `${row.pct}%`}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
