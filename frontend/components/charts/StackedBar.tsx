import type { CSSProperties } from 'react';
import { ChartTable, type ChartTableData } from './ChartTable';
import styles from './StackedBar.module.css';

// One bar split by share. Each segment has a pattern as well as a colour (solid, hatched, dashed), and the legend
// says the glyph, the word and the number of every segment, a zero one included. No chart library.

export type StackedSegment = {
  key: string;
  label: string;
  value: number;
  /** A shape character that goes before the word in the legend, for example "●". */
  glyph?: string;
  tone: 'primary' | 'limited' | 'closed' | 'surge' | 'unknown';
  pattern: 'solid' | 'hatch' | 'dashed';
};

export function StackedBar({
  label,
  segments,
  unit = '',
  note,
  table,
}: {
  /** The shares in words: the accessible name of the bar. */
  label: string;
  segments: readonly StackedSegment[];
  /** Printed after each number in the legend, for example "%". */
  unit?: string;
  /** A line under the legend, for example what is not shown and why. */
  note?: string;
  table: ChartTableData;
}) {
  return (
    <div className={styles.root}>
      <div role="img" aria-label={label} className={styles.bar}>
        {segments
          .filter((s) => s.value > 0)
          .map((s) => (
            <span
              key={s.key}
              data-segment
              data-tone={s.tone}
              data-pattern={s.pattern}
              className={styles.segment}
              style={{ flexGrow: s.value, flexBasis: 0 } as CSSProperties}
            />
          ))}
      </div>
      <ul aria-label="Legend" className={styles.legend}>
        {segments.map((s) => (
          <li key={s.key} className={styles.item}>
            <i className={styles.swatch} data-tone={s.tone} data-pattern={s.pattern} aria-hidden="true" />
            <span>
              {s.glyph ? `${s.glyph} ` : ''}
              {s.label} {s.value}
              {unit}
            </span>
          </li>
        ))}
      </ul>
      {note ? <p className={styles.note}>{note}</p> : null}
      <ChartTable table={table} />
    </div>
  );
}
