import type { ReactNode } from 'react';
import styles from './DiffTable.module.css';

// What changed: one row per thing (what / was / now), then one "Everything else" row that says the rest is
// the same. The new value is marked by its amber box and heavier weight; the arrow is decoration.

export type DiffRow = { id: string; what: ReactNode; was: ReactNode; now: ReactNode };

export type DiffTableProps = {
  /** The accessible name of the table. */
  label: string;
  rows: readonly DiffRow[];
  wasLabel?: string;
  nowLabel?: string;
  /** The sentence for the "Everything else" row. Leave out to draw no such row. */
  same?: string;
};

export function DiffTable({ label, rows, wasLabel = 'Was', nowLabel = 'Now', same }: DiffTableProps) {
  return (
    <table className={styles.table} aria-label={label}>
      <thead>
        <tr>
          <th scope="col">What</th>
          <th scope="col">{wasLabel}</th>
          <th scope="col">{nowLabel}</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row.id}>
            <th scope="row" className={styles.what}>
              {row.what}
            </th>
            <td className={styles.was}>
              <span className={styles.box}>{row.was}</span>
            </td>
            <td className={styles.now}>
              <span className={styles.box}>{row.now}</span>
            </td>
          </tr>
        ))}
        {same === undefined ? null : (
          <tr className={styles.same}>
            <th scope="row" className={styles.what}>
              Everything else
            </th>
            <td colSpan={2}>{same}</td>
          </tr>
        )}
      </tbody>
    </table>
  );
}
