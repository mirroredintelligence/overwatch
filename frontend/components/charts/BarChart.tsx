import { ChartTable, type ChartTableData } from './ChartTable';
import styles from './BarChart.module.css';

// CSS flex bars on an axis that starts at zero, the value on every bar, an optional threshold line with its own
// words, and the same rows as a table behind "Show as a table". No chart library (planning brief, shared piece 8).

export type BarChartBar = { label: string; value: number; flagged?: boolean };

export function BarChart({
  label,
  bars,
  threshold,
  max,
  table,
}: {
  /** The finding in words: the accessible name of the chart. */
  label: string;
  bars: readonly BarChartBar[];
  /** A dashed line at a value, named in words (never colour alone). */
  threshold?: { value: number; label: string };
  /** The top of the scale; by default one above the biggest value, so the tallest bar leaves room for its number. */
  max?: number;
  table: ChartTableData;
}) {
  const top = Math.max(1, max ?? Math.max(0, threshold?.value ?? 0, ...bars.map((b) => b.value)) + 1);
  const share = (v: number) => Math.min(1, Math.max(0, v / top));
  return (
    <div className={styles.root}>
      <div role="img" aria-label={label} className={styles.chart}>
        <div className={styles.plot}>
          {threshold ? (
            <>
              <div data-threshold className={styles.threshold} data-css={JSON.stringify({ bottom: `${share(threshold.value) * 100}%` })} />
              <span className={styles.thresholdLabel} data-css={JSON.stringify({ bottom: `calc(${share(threshold.value) * 100}% + 4px)` })}>
                {threshold.label}
              </span>
            </>
          ) : null}
          {bars.map((b) => (
            <div
              key={b.label}
              data-bar
              data-flagged={b.flagged ? 'true' : undefined}
              className={styles.bar}
              data-css={JSON.stringify({ '--share': share(b.value) })}
            >
              <b className={styles.value}>{b.value}</b>
              <i className={styles.fill} />
            </div>
          ))}
        </div>
        <div className={styles.labels}>
          {bars.map((b) => (
            <span key={b.label} className={styles.tick} data-flagged={b.flagged ? 'true' : undefined}>
              {b.label}
              {b.flagged ? <span className={styles.sr}>at the alert level</span> : null}
            </span>
          ))}
        </div>
      </div>
      <ChartTable table={table} />
    </div>
  );
}
