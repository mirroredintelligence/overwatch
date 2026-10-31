import type { ReactNode } from 'react';
import styles from './Parts.module.css';

// Label and value rows in one card (artboards OnboardReporter2 "All set", ReporterApp2 "Settings"). A
// description list, so a screen reader pairs each label with its value.

export type SummaryRow = { label: string; value: ReactNode };

export function SummaryRows({ rows, dataEl }: { rows: readonly SummaryRow[]; dataEl?: string }) {
  return (
    <dl className={styles.rows} data-el={dataEl}>
      {rows.map((row) => (
        <div key={row.label} className={styles.row}>
          <dt className={styles.rowLabel}>{row.label}</dt>
          <dd className={styles.rowValue}>{row.value}</dd>
        </div>
      ))}
    </dl>
  );
}
