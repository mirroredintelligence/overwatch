import { ChartTable, type ChartTableData } from './ChartTable';
import styles from './PressureStrip.module.css';

// A grid of days by 24 hours. Each cell is a level: normal (plain), watch (hatched) or high (solid and outlined),
// so no level is told apart by colour alone; the legend gives each a word and the table gives every hour.

export type PressureLevel = 'normal' | 'watch' | 'high' | 'none';

const HOURS = 24;
const HOUR_MARKS = ['00', '06', '12', '18'];
const LEGEND: readonly { level: PressureLevel; word: string }[] = [
  { level: 'normal', word: 'Normal' },
  { level: 'watch', word: 'Watch' },
  { level: 'high', word: 'High' },
  { level: 'none', word: 'Not sampled' },
];

export function PressureStrip({
  label,
  rows,
  table,
}: {
  /** The finding in words: the accessible name of the grid. */
  label: string;
  rows: readonly { label: string; levels: readonly PressureLevel[] }[];
  table: ChartTableData;
}) {
  return (
    <div className={styles.root}>
      <div role="img" aria-label={label} className={styles.chart}>
        <div className={styles.line}>
          <span />
          {HOUR_MARKS.map((h) => (
            <span key={h} className={styles.mark}>
              {h}
            </span>
          ))}
        </div>
        {rows.map((row) => (
          <div key={row.label} data-row className={styles.line}>
            <span className={styles.day}>{row.label}</span>
            {Array.from({ length: HOURS }, (_, h) => (
              <i key={h} data-cell data-level={row.levels[h] ?? 'none'} className={styles.cell} />
            ))}
          </div>
        ))}
      </div>
      <ul aria-label="Legend" className={styles.legend}>
        {LEGEND.map((l) => (
          <li key={l.level} className={styles.item}>
            <i data-level={l.level} className={styles.swatch} aria-hidden="true" />
            <span>{l.word}</span>
          </li>
        ))}
      </ul>
      <ChartTable table={table} />
    </div>
  );
}
