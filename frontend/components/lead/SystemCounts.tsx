import type { SystemCounts as Counts } from '@/lib/lead/types';
import { servicesWord } from '@/lib/lead/format';
import styles from './SystemCounts.module.css';

// The system now (W17): each count with its word and its shape (accepting a filled circle, limited a square,
// over capacity a diamond, not accepting a dark filled circle, not updated a dashed circle). The figures are
// plain text and never animate. The network variant is not built yet (the tenancy amendment for W17 is a later
// task); these are the organisation's own counts.

type Shape = 'circle' | 'square' | 'diamond' | 'dark-circle' | 'dashed-circle';

export function SystemCounts({ counts, reportingToday }: { counts: Counts; reportingToday: number }) {
  const rows: [string, number, Shape][] = [
    ['Accepting', counts.accepting, 'circle'],
    ['Limited', counts.limited, 'square'],
    ['Over capacity', counts.overCapacity, 'diamond'],
    ['Not accepting', counts.notAccepting, 'dark-circle'],
    ['Not updated', counts.notUpdated, 'dashed-circle'],
  ];
  return (
    <section className={styles.card} aria-labelledby="lead-system-heading" data-el="LEAD-SYSTEM">
      <h2 id="lead-system-heading" className={styles.heading}>
        System now
      </h2>
      <dl className={styles.counts}>
        {rows.map(([word, n, shape]) => (
          <div key={word} className={styles.row}>
            <dt className={styles.word}>
              <span className={styles.mark} data-shape={shape} aria-hidden="true" />
              {word}
            </dt>
            <dd className={styles.figure} data-state={shape}>
              {n}
            </dd>
          </div>
        ))}
      </dl>
      <p className={styles.reporting}>{`${reportingToday} ${servicesWord(reportingToday)} reporting today`}</p>
    </section>
  );
}
