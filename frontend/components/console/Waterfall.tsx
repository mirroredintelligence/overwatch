import { formatMs, layoutSpan, QUERY_BUDGET_MS, type SpanView } from '@/lib/console/trace';
import styles from './Console.module.css';

// A trace as bars on one time line, with the same spans as a table so no timing is only a picture
// (W48). Each bar is placed by its offset and duration, scaled to the trace's total.

export function Waterfall({ totalMs, spans }: { totalMs: number; spans: readonly SpanView[] }) {
  return (
    <div>
      <div className={styles.waterfall} aria-hidden="true">
        {spans.map((span) => {
          const { leftPct, widthPct } = layoutSpan(span, totalMs);
          return (
            <div key={span.spanId} className={styles.row}>
              <div
                className={styles.bar}
                data-span={span.spanId}
                data-status={span.status === 'ok' ? 'ok' : 'error'}
                style={{ left: `${leftPct}%`, width: `${widthPct}%` }}
              />
            </div>
          );
        })}
      </div>
      <table className={styles.table} aria-label="Spans">
        <thead>
          <tr>
            <th scope="col">Span</th>
            <th scope="col">Duration</th>
            <th scope="col">Status</th>
          </tr>
        </thead>
        <tbody>
          {spans.map((span) => (
            <tr key={span.spanId}>
              <td>{span.name}</td>
              <td>{formatMs(span.durationMs)}</td>
              <td>{span.status === 'ok' ? 'Success' : 'Error'}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className={styles.help}>Budget for this query is {QUERY_BUDGET_MS} ms.</p>
    </div>
  );
}
