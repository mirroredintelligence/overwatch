import type { SystemCounts as Counts } from '@/lib/lead/types';
import { servicesWord } from '@/lib/lead/format';
import styles from './Lead.module.css';

// The system now (W17): each count with its word. The network variant is not built yet (the tenancy
// amendment for W17 is a later task); these are the organisation's own counts.

export function SystemCounts({ counts, reportingToday }: { counts: Counts; reportingToday: number }) {
  const rows: [string, number][] = [
    ['Accepting', counts.accepting],
    ['Limited', counts.limited],
    ['Not accepting', counts.notAccepting],
    ['Over capacity', counts.overCapacity],
    ['Not updated', counts.notUpdated],
  ];
  return (
    <section className={styles.section} aria-labelledby="lead-system-heading" data-el="LEAD-SYSTEM">
      <h2 id="lead-system-heading" className={styles.sectionHeading}>
        System now
      </h2>
      <dl className={styles.counts}>
        {rows.map(([word, n]) => (
          <div key={word} className={styles.count}>
            <dt>{word}</dt>
            <dd>{n}</dd>
          </div>
        ))}
      </dl>
      <p className={styles.muted}>{`${reportingToday} ${servicesWord(reportingToday)} reporting today`}</p>
    </section>
  );
}
