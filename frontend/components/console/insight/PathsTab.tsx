import type { PathRow } from '@/lib/console/insight';
import styles from '../Console.module.css';
import insight from './Insight.module.css';

// Navigation paths (W49): the common route templates, the U-turns and the elements no one used.

export function PathsTab({
  mostCommon,
  uTurns,
  unused,
}: {
  mostCommon: readonly PathRow[];
  uTurns: readonly PathRow[];
  /** The controls nobody used, or null when the back end cannot say (it does not hold the list of controls). */
  unused: readonly string[] | null;
}) {
  return (
    <section className={insight.panel} aria-label="Paths">
      <div className={insight.scroll}>
        <table className={styles.table} aria-label="Most common routes table">
          <caption className={`${insight.eyebrow} ${insight.caption}`}>Most common routes</caption>
          <thead>
            <tr>
              <th scope="col">Route</th>
              <th scope="col">Sessions</th>
              <th scope="col">Median time</th>
            </tr>
          </thead>
          <tbody>
            {mostCommon.map((row) => (
              <tr key={row.route}>
                <td>{row.route}</td>
                <td>{row.suppressed || row.sessions === null ? 'fewer than 10' : row.sessions}</td>
                <td>{row.medianSeconds === null ? '' : `${row.medianSeconds} s`}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <section aria-labelledby="paths-uturns">
        <h2 id="paths-uturns" className={insight.subheading}>U-turns: left within 5 s</h2>
        <ul>
          {uTurns.map((row) => (
            <li key={row.route}>{row.route}: {row.suppressed || row.sessions === null ? 'fewer than 10' : row.sessions}</li>
          ))}
        </ul>
      </section>
      <section aria-labelledby="paths-unused">
        <h2 id="paths-unused" className={insight.subheading}>Never used this week</h2>
        {unused === null ? (
          <p className={styles.help}>Not measured yet: this needs the list of every control.</p>
        ) : (
          <ul>
            {unused.map((elementId) => (
              <li key={elementId}>{elementId}</li>
            ))}
          </ul>
        )}
      </section>
    </section>
  );
}
