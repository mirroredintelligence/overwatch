import type { FrictionRow } from '@/lib/console/insight';
import styles from '../Console.module.css';
import insight from './Insight.module.css';

// Friction by element (W49). An element the back end flags for review (over 5%) is marked with a shape
// and the word, so the colour is never the only signal. The page takes the flag as it is sent: the rule
// is the back end's (strictly over 5%), and friction of the page itself has a route and no rate.
// No "show example sessions" link: no route serves example sessions, so the board's element is not drawn.

function percent(rate: number): string {
  return `${Math.round(rate * 100)}%`;
}

function hiddenNote(count: number): string {
  return count === 1
    ? '1 element or page with fewer than 10 sessions is not shown.'
    : `${count} elements or pages with fewer than 10 sessions are not shown.`;
}

export function FrictionTab({ rows, suppressedGroups }: { rows: readonly FrictionRow[]; suppressedGroups: number }) {
  return (
    <section className={insight.panel} aria-labelledby="friction-heading">
      <h2 id="friction-heading" className={insight.eyebrow}>Friction by element</h2>
      <p className={styles.help}>Elements over 5% are reviewed.</p>
      {suppressedGroups > 0 && <p className={styles.help}>{hiddenNote(suppressedGroups)}</p>}
      <div className={insight.scroll}>
        <table className={styles.table} aria-label="Friction by element table">
          <thead>
            <tr>
              <th scope="col">Element</th>
              <th scope="col">Kind</th>
              <th scope="col">Events</th>
              <th scope="col">Rate</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={`${row.elementId}-${row.kind}-${row.route ?? ''}`} data-flagged={row.review ? '' : undefined}>
                <td>{row.route === null ? row.elementId : `${row.elementId} ${row.route}`}</td>
                <td>{row.kind}</td>
                <td>{row.events}</td>
                <td>
                  {row.rate === null ? '–' : <b>{percent(row.rate)}</b>}
                  {row.review && (
                    <>
                      {' '}
                      <span className={insight.bad}>
                        <span aria-hidden="true">▲ </span>Review
                      </span>
                    </>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
