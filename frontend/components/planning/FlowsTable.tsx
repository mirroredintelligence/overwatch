import { share } from '@/lib/planning/share';
import type { Flow } from '@/lib/planning/types';
import layout from './Planning.module.css';
import { StyledDiv } from '@/components/ui/Styled';

// Where they went when the best fit was full (W51). A share is of the referrals whose best fit was
// unavailable (total). A suppressed row reads "under 10", has no share and no bar, and says "hidden".

const STATES: Record<string, string> = { full: 'Full', closed: 'Closed', 'not-updated': 'Not updated' };

export function FlowsTable({ flows, total }: { flows: readonly Flow[]; total: number | null }) {
  return (
    <section aria-labelledby="flows-heading" className={layout.card}>
      <h2 id="flows-heading" className={layout.cardTitle}>Where they went when the best fit was full</h2>
      <div className={layout.scroll}>
        <table className={`${layout.table} ${layout.flowsTable}`} aria-label="Where they went when the best fit was full table">
          <thead>
            <tr>
              <th scope="col">Best fit, and its state</th>
              <th scope="col">Went to</th>
              <th scope="col" className={layout.num}>Referrals</th>
              <th scope="col">Share</th>
            </tr>
          </thead>
          <tbody>
            {flows.map((flow) => {
              const hidden = flow.suppressed || flow.count === null;
              const pct = hidden || total === null ? null : share(flow.count, total);
              return (
                <tr key={`${flow.bestFit}-${flow.wentTo}`}>
                  <td>
                    {flow.bestFit} · {STATES[flow.state] ?? flow.state}
                  </td>
                  <td>{flow.wentTo}</td>
                  <td className={`${layout.num} ${hidden ? layout.small : ''}`}>{hidden ? 'under 10' : flow.count}</td>
                  <td>
                    {pct === null ? (
                      hidden ? <span className={layout.small}>hidden</span> : null
                    ) : (
                      <div className={layout.share}>
                        <div className={layout.bar} aria-hidden="true">
                          <StyledDiv data-bar className={layout.barFill} css={{ width: `${pct}%` }} />
                        </div>
                        <span>{pct}%</span>
                      </div>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className={layout.note}>Counts under 10 are not shown, to protect small groups.</p>
      <p className={layout.note}>Bars start at zero.</p>
    </section>
  );
}
