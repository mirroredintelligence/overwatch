import Link from 'next/link';
import type { FrictionRow } from '@/lib/console/insight';
import styles from '../Console.module.css';

// Friction by element (W49). An element at or over 5% is marked for review with a shape and the
// word, so the colour is never the only signal.

export const REVIEW_AT = 0.05;

function percent(rate: number): string {
  return `${Math.round(rate * 100)}%`;
}

export function FrictionTab({ rows }: { rows: readonly FrictionRow[] }) {
  return (
    <section className={styles.section} aria-labelledby="friction-heading">
      <h2 id="friction-heading" className={styles.heading}>Friction by element</h2>
      <p className={styles.help}>Elements over 5% are reviewed.</p>
      <table className={styles.table} aria-label="Friction by element table">
        <thead>
          <tr>
            <th scope="col">Element</th>
            <th scope="col">Kind</th>
            <th scope="col">Events</th>
            <th scope="col">Interactions</th>
            <th scope="col">Rate</th>
            <th scope="col">Review</th>
            <th scope="col">Examples</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const review = row.rate >= REVIEW_AT;
            return (
              <tr key={`${row.elementId}-${row.kind}`}>
                <td>{row.elementId}</td>
                <td>{row.kind}</td>
                <td>{row.events}</td>
                <td>{row.interactions}</td>
                <td>{percent(row.rate)}</td>
                <td>{review ? <span><span aria-hidden="true">▲ </span>Review</span> : null}</td>
                <td>
                  <Link href={`/console?element=${encodeURIComponent(row.elementId)}`} data-el="CON-INS-EXAMPLES-BTN">
                    Show example sessions
                  </Link>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </section>
  );
}
