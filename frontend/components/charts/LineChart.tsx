import { ChartTable, type ChartTableData } from './ChartTable';
import styles from './LineChart.module.css';

// An inline SVG polyline on an axis that starts at zero: the peak carries its number, the threshold is a dashed line
// with its own words, and the same rows sit behind "Show as a table". No chart library.

export type LineChartPoint = { label: string; value: number };

const X0 = 30;
const X1 = 390;
const Y0 = 110;
const Y1 = 10;

export function LineChart({
  label,
  points,
  threshold,
  max,
  table,
}: {
  /** The finding in words: the accessible name of the chart. */
  label: string;
  points: readonly LineChartPoint[];
  threshold?: { value: number; label: string };
  /** The top of the scale; by default two above the biggest value, so the peak and its number have room. */
  max?: number;
  table: ChartTableData;
}) {
  const top = Math.max(1, max ?? Math.max(0, threshold?.value ?? 0, ...points.map((p) => p.value)) + 2);
  const x = (i: number) => (points.length < 2 ? (X0 + X1) / 2 : X0 + (i * (X1 - X0)) / (points.length - 1));
  const y = (v: number) => Y0 - (Math.min(top, Math.max(0, v)) / top) * (Y0 - Y1);
  const peakAt = points.reduce((best, p, i) => (p.value > points[best].value ? i : best), 0);
  const peak = points[peakAt];
  const ticks = Array.from(new Set([0, Math.floor((points.length - 1) / 2), points.length - 1])).filter((i) => i >= 0 && i < points.length);
  return (
    <div className={styles.root}>
      <svg viewBox="0 0 400 130" width="100%" role="img" aria-label={label} className={styles.svg}>
        <line x1={X0} y1={Y0} x2={X1} y2={Y0} className={styles.axis} />
        <line x1={X0} y1={Y1} x2={X0} y2={Y0} className={styles.axis} />
        <text x={X0 - 6} y={Y0 + 4} textAnchor="end" className={styles.tick}>
          0
        </text>
        {threshold ? (
          <>
            <line data-threshold x1={X0} y1={y(threshold.value)} x2={X1} y2={y(threshold.value)} className={styles.threshold} strokeDasharray="6 5" />
            <text x={X1} y={y(threshold.value) - 4} textAnchor="end" className={styles.thresholdLabel}>
              {threshold.label}
            </text>
          </>
        ) : null}
        {points.length > 0 ? (
          <>
            <polyline fill="none" strokeLinejoin="round" className={styles.line} points={points.map((p, i) => `${x(i)},${y(p.value)}`).join(' ')} />
            <circle cx={x(peakAt)} cy={y(peak.value)} r={5} className={styles.peakDot} />
            <text data-peak x={x(peakAt)} y={y(peak.value) - 12} textAnchor="middle" className={styles.peak}>
              {peak.value}
            </text>
          </>
        ) : null}
        {ticks.map((i) => (
          <text key={i} x={x(i)} y={126} textAnchor={i === 0 ? 'start' : i === points.length - 1 ? 'end' : 'middle'} className={styles.tick}>
            {points[i].label}
          </text>
        ))}
      </svg>
      <ChartTable table={table} />
    </div>
  );
}
