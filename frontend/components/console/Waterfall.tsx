import type { ReactNode } from 'react';
import { formatMs, layoutSpan, QUERY_BUDGET_MS, slowestSpan, type SpanView } from '@/lib/console/trace';
import styles from './Console.module.css';
import own from './Waterfall.module.css';
import { StyledDiv } from '@/components/ui/Styled';

// A trace as bars on one time line, with the same spans as a table so no timing is only a picture
// (W48). Each bar is placed by its offset and duration, scaled to the trace's total. The slowest step
// is the slowest span under the request itself: the request span always lasts longest, so it is left
// out, and the step that took longest is hatched and named in words.

export function Waterfall({
  totalMs,
  spans,
  actions,
}: {
  totalMs: number;
  spans: readonly SpanView[];
  actions?: ReactNode;
}) {
  if (spans.length === 0) {
    return <p className={styles.help}>No spans were recorded for this trace.</p>;
  }

  const slowest = slowestSpan(spans.filter((span) => span.parentSpanId !== null));
  const total = formatMs(totalMs);
  const finding =
    slowest === null
      ? `The trace has ${spans.length} span and no steps inside it.`
      : `The slowest step is ${slowest.name}, ${formatMs(slowest.durationMs)}, of ${total}.`;

  return (
    <div className={own.layout}>
      <section className={own.card} aria-labelledby="console-waterfall">
        <div>
          <h2 id="console-waterfall" className={own.eyebrow}>
            Where the {total} went
          </h2>
          <p className={own.subtitle}>0 to {total}, from the start of the trace</p>
        </div>
        <div role="img" aria-label={`Waterfall of ${spans.length} spans over ${total}. ${finding}`}>
          {spans.map((span) => {
            const { leftPct, widthPct } = layoutSpan(span, totalMs);
            const isSlowest = slowest !== null && span.spanId === slowest.spanId;
            return (
              <div key={span.spanId} className={own.row} data-slowest={isSlowest ? 'true' : 'false'}>
                <span className={own.label}>{span.name}</span>
                <span className={own.time}>{formatMs(span.durationMs)}</span>
                <div className={own.track}>
                  <StyledDiv
                    className={own.bar}
                    data-span={span.spanId}
                    data-status={span.status === 'ok' ? 'ok' : 'error'}
                    data-slowest={isSlowest ? 'true' : 'false'}
                    css={{ left: `${leftPct}%`, width: `${widthPct}%` }}
                  />
                </div>
              </div>
            );
          })}
        </div>
        <p className={styles.help}>
          Bars start at the start of the trace. The slowest step is hatched and named in words beside the chart.
        </p>
      </section>

      <div className={own.side}>
        <section className={`${own.card} ${slowest === null ? '' : own.slowestCard}`} aria-labelledby="console-slowest">
          <h2 id="console-slowest" className={own.eyebrow}>
            Slowest
          </h2>
          {slowest === null ? (
            <p>Only the request itself was recorded, with no steps inside it.</p>
          ) : (
            <p>
              {slowest.name} took {formatMs(slowest.durationMs)}. The budget for this query is {QUERY_BUDGET_MS} ms.
            </p>
          )}
        </section>

        <section className={own.card} aria-labelledby="console-spans">
          <h2 id="console-spans" className={own.eyebrow}>
            Spans as a table
          </h2>
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
        </section>

        {actions !== undefined && <div className={own.actions}>{actions}</div>}
        <p className={styles.help}>Spans carry names, durations and counts. They never carry values the person entered.</p>
      </div>
    </div>
  );
}
