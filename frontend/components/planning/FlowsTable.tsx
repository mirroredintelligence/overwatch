import { share } from '@/lib/planning/share';
import type { Flow } from '@/lib/planning/types';
import styles from '../console/Console.module.css';

// Where they went when the best fit was full (W51). A share is of the referrals whose best fit was
// unavailable (total). A suppressed row shows "fewer than 10" and has no share and no bar.

const STATES: Record<string, string> = { full: 'Full', closed: 'Closed', 'not-updated': 'Not updated' };

export function FlowsTable({ flows, total }: { flows: readonly Flow[]; total: number }) {
  return (
    <section aria-labelledby="flows-heading">
      <h2 id="flows-heading" className={styles.heading}>Where they went when the best fit was full</h2>
      <table className={styles.table} aria-label="Where they went when the best fit was full table">
        <thead>
          <tr>
            <th scope="col">Best fit and its state</th>
            <th scope="col">Went to</th>
            <th scope="col">Referrals</th>
            <th scope="col">Share</th>
          </tr>
        </thead>
        <tbody>
          {flows.map((flow) => {
            const pct = flow.suppressed ? null : share(flow.count, total);
            return (
              <tr key={`${flow.bestFit}-${flow.wentTo}`}>
                <td>
                  {flow.bestFit}, {STATES[flow.state] ?? flow.state}
                </td>
                <td>{flow.wentTo}</td>
                <td>{flow.suppressed || flow.count === null ? 'fewer than 10' : flow.count}</td>
                <td>
                  {pct === null ? null : (
                    <>
                      <span>{pct}%</span>
                      <div
                        data-bar
                        aria-hidden="true"
                        style={{ width: `${pct}%`, height: '0.75rem', background: 'var(--c-primary)', borderRadius: 'var(--radius-chip)' }}
                      />
                    </>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className={styles.help}>Counts under 10 are not shown, to protect small groups.</p>
    </section>
  );
}
