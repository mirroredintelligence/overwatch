import { ChartTable, type ChartTableData } from './ChartTable';
import styles from './Funnel.module.css';

// CSS bars that start at zero, one per step, each with its word and its number. The biggest drop between two
// steps is hatched and named in words. No chart library.

export type FunnelStep = { label: string; value: number };

export function Funnel({
  label,
  steps,
  unit = '',
  table,
}: {
  /** What the funnel shows, in words: the accessible name of the chart. */
  label: string;
  steps: readonly FunnelStep[];
  /** Printed after each number, for example "%". Bar widths are the values as a share of 100. */
  unit?: string;
  table: ChartTableData;
}) {
  const drops = steps.map((s, i) => (i === 0 ? 0 : steps[i - 1].value - s.value));
  let biggest = -1;
  drops.forEach((d, i) => {
    if (d > 0 && (biggest < 0 || d > drops[biggest])) biggest = i;
  });
  return (
    <div className={styles.root}>
      <div role="img" aria-label={label} className={styles.chart}>
        {steps.map((s, i) => (
          <div key={s.label} className={styles.row} data-biggest={i === biggest ? 'true' : undefined}>
            <span className={styles.name}>{s.label}</span>
            <i
              data-step-bar
              data-step={i}
              data-biggest={i === biggest ? 'true' : undefined}
              className={styles.bar}
              data-css={JSON.stringify({ width: `${Math.min(100, Math.max(0, s.value))}%` })}
            />
            <b className={styles.value}>
              {s.value}
              {unit}
            </b>
            <small className={styles.drop}>{i === 0 || drops[i] <= 0 ? '' : i === biggest ? `−${drops[i]} biggest` : `−${drops[i]}`}</small>
          </div>
        ))}
      </div>
      {biggest > 0 ? (
        <p className={styles.note}>
          Biggest drop: {steps[biggest - 1].label} to {steps[biggest].label}, {drops[biggest]} points.
        </p>
      ) : null}
      <ChartTable table={table} />
    </div>
  );
}
