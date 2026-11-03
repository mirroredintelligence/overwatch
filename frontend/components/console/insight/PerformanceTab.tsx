import { budgetStatus } from '@/lib/console/budget';
import type { Slow, Vital } from '@/lib/console/insight';
import styles from '../Console.module.css';
import insight from './Insight.module.css';

// Performance against budgets (W49). Each status is a word from budgetStatus, with a shape beside it: a dot
// within the budget, a triangle over it. A row over budget is tinted, as the friction rows are.

type Props = {
  vitals: readonly Vital[];
  slowestRoutes: readonly Slow[];
  slowestQueries: readonly Slow[];
  promptToBoard: { systemSeconds: number; humanMinutes: number } | null;
};

function show(value: number, unit: Vital['unit']): string {
  return unit === 'ms' ? `${Math.round(value)} ms` : String(value);
}

export function PerformanceTab({ vitals, slowestRoutes, slowestQueries, promptToBoard }: Props) {
  return (
    <section className={insight.panel} aria-label="Performance">
      <div className={insight.scroll}>
        <table className={styles.table} aria-label="Web vitals table">
          <caption className={`${insight.eyebrow} ${insight.caption}`}>Web vitals, p75 against budget</caption>
          <thead>
            <tr>
              <th scope="col">Measure</th>
              <th scope="col">Device</th>
              <th scope="col">p75</th>
              <th scope="col">Budget</th>
              <th scope="col">Status</th>
            </tr>
          </thead>
          <tbody>
            {vitals.map((vital) => {
              if (vital.suppressed || vital.p75 === null) {
                return (
                  <tr key={`${vital.metric}-${vital.device}`}>
                    <td>{vital.measure}</td>
                    <td>{vital.device}</td>
                    <td>fewer than 10</td>
                    <td>{show(vital.budget, vital.unit)}</td>
                    <td></td>
                  </tr>
                );
              }
              const status = budgetStatus(vital.p75, vital.budget);
              const over = status === 'Over budget';
              return (
                <tr key={`${vital.metric}-${vital.device}`} data-flagged={over ? '' : undefined}>
                  <td>{vital.measure}</td>
                  <td>{vital.device}</td>
                  <td>
                    <b>{show(vital.p75, vital.unit)}</b>
                  </td>
                  <td>{show(vital.budget, vital.unit)}</td>
                  <td>
                    <span className={over ? insight.bad : insight.ok}>
                      <span aria-hidden="true">{over ? '▲ ' : '● '}</span>
                      {status}
                    </span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <section aria-labelledby="routes-heading">
        <h2 id="routes-heading" className={insight.subheading}>Slowest routes</h2>
        <ol>
          {slowestRoutes.map((route) => (
            <li key={route.name}>{route.name}: p95 {Math.round(route.p95Ms)} ms</li>
          ))}
        </ol>
        <h2 className={insight.subheading}>Slowest Cypher queries</h2>
        <ol>
          {slowestQueries.map((query) => (
            <li key={query.name}>{query.name}: p95 {Math.round(query.p95Ms)} ms</li>
          ))}
        </ol>
      </section>
      {promptToBoard === null ? (
        <p className={styles.help}>Prompt to board: not measured yet.</p>
      ) : (
        <p>
          Prompt to board: system time {promptToBoard.systemSeconds} s, human time {promptToBoard.humanMinutes} min.
        </p>
      )}
    </section>
  );
}
