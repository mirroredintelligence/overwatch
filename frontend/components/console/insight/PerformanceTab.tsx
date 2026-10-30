import { budgetStatus } from '@/lib/console/budget';
import type { Slow, Vital } from '@/lib/console/insight';
import styles from '../Console.module.css';

// Performance against budgets (W49). Each status is a word from budgetStatus.

type Props = {
  vitals: readonly Vital[];
  slowestRoutes: readonly Slow[];
  slowestQueries: readonly Slow[];
  promptToBoard: { systemSeconds: number; humanMinutes: number } | null;
};

function show(value: number, unit: Vital['unit']): string {
  if (unit === 'ms') return `${Math.round(value)} ms`;
  if (unit === 's') return `${value} s`;
  return String(value);
}

export function PerformanceTab({ vitals, slowestRoutes, slowestQueries, promptToBoard }: Props) {
  return (
    <div className={styles.page}>
      <section className={styles.section} aria-labelledby="vitals-heading">
        <h2 id="vitals-heading" className={styles.heading}>Web vitals</h2>
        <table className={styles.table} aria-label="Web vitals table">
          <thead>
            <tr>
              <th scope="col">Measure</th>
              <th scope="col">p75</th>
              <th scope="col">Budget</th>
              <th scope="col">Status</th>
            </tr>
          </thead>
          <tbody>
            {vitals.map((vital) => (
              <tr key={vital.measure}>
                <td>{vital.measure}</td>
                <td>{show(vital.p75, vital.unit)}</td>
                <td>{show(vital.budget, vital.unit)}</td>
                <td>{budgetStatus(vital.p75, vital.budget)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
      <section className={styles.section} aria-labelledby="routes-heading">
        <h2 id="routes-heading" className={styles.heading}>Slowest routes</h2>
        <ol>
          {slowestRoutes.map((route) => (
            <li key={route.name}>{route.name}: p95 {Math.round(route.p95Ms)} ms</li>
          ))}
        </ol>
        <h2 className={styles.heading}>Slowest Cypher queries</h2>
        <ol>
          {slowestQueries.map((query) => (
            <li key={query.name}>{query.name}: p95 {Math.round(query.p95Ms)} ms</li>
          ))}
        </ol>
      </section>
      {promptToBoard !== null && (
        <p>
          Prompt to board: System time {promptToBoard.systemSeconds} s, Human time {promptToBoard.humanMinutes} min
        </p>
      )}
    </div>
  );
}
