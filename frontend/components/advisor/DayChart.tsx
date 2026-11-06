'use client';

import { useEffect, useId, useState } from 'react';
import { chartSummary, parseHistory, stretchesOf, type History } from '@/lib/advisor/history';
import { clockTime } from '@/lib/lead/format';
import styles from './DayChart.module.css';

// What a service reported over the last day (DEC-1343), as a stepped line that breaks where its capacity was unknown:
// a figure counts only for the stale limit after its report, and nothing is drawn past that until the next report.
// The gap is hatched and labelled in words, so it never depends on colour. The same figures are in a table under it.
// A chart that cannot be read says so and shows nothing; it never draws a guess.

const WIDTH = 640;
const HEIGHT = 200;
const PAD = { left: 40, right: 12, top: 14, bottom: 30 };

type State = { kind: 'loading' } | { kind: 'ready'; history: History } | { kind: 'failed' };

function path(history: History, x: (time: number) => number, y: (value: number) => number): string {
  const { known } = stretchesOf(history);
  let d = '';
  let previousEnd: number | null = null;
  for (const stretch of known) {
    const value = stretch.available ?? 0;
    d += previousEnd === stretch.from ? ` V ${y(value)}` : ` M ${x(stretch.from)} ${y(value)}`;
    d += ` H ${x(stretch.to)}`;
    previousEnd = stretch.to;
  }
  return d.trim();
}

export function DayChart({ serviceId }: { serviceId: string }) {
  const [state, setState] = useState<State>({ kind: 'loading' });
  const patternId = useId();

  useEffect(() => {
    const controller = new AbortController();
    fetch(`/api/bff/advisor/services/${encodeURIComponent(serviceId)}/history`, {
      cache: 'no-store',
      credentials: 'same-origin',
      signal: controller.signal,
    })
      .then(async (response) => {
        if (!response.ok) throw new Error('refused');
        setState({ kind: 'ready', history: parseHistory(await response.json()) });
      })
      .catch(() => {
        if (!controller.signal.aborted) setState({ kind: 'failed' });
      });
    return () => controller.abort();
  }, [serviceId]);

  if (state.kind === 'loading') return <p className={styles.note}>Loading the day.</p>;
  if (state.kind === 'failed') return <p className={styles.note}>The day could not be read. Nothing is drawn.</p>;

  const history = state.history;
  const since = Date.parse(history.since);
  const until = Date.parse(history.until);
  const span = Math.max(until - since, 1);
  const top = Math.max(history.established, ...history.points.map((point) => point.available ?? 0), 1);
  const x = (time: number) => Math.round((PAD.left + ((time - since) / span) * (WIDTH - PAD.left - PAD.right)) * 10) / 10;
  const y = (value: number) => Math.round((PAD.top + (1 - value / top) * (HEIGHT - PAD.top - PAD.bottom)) * 10) / 10;
  const { unknown } = stretchesOf(history);
  const gaps = unknown.filter((gap) => gap.to - gap.from >= 60_000);
  const widest = gaps.reduce<{ from: number; to: number } | null>((best, gap) => (best === null || gap.to - gap.from > best.to - best.from ? gap : best), null);
  const ticks = [since, since + span / 2, until];

  return (
    <figure className={styles.figure} data-el="ADV-DAY-CHART">
      <figcaption className={styles.caption}>{`Reported figures, last 24 hrs (${history.unitLabel})`}</figcaption>
      <svg className={styles.chart} viewBox={`0 0 ${WIDTH} ${HEIGHT}`} role="img" aria-label={chartSummary(history)}>
        <defs>
          <pattern id={patternId} patternUnits="userSpaceOnUse" width="8" height="8" patternTransform="rotate(45)">
            <line className={styles.hatch} x1="0" y1="0" x2="0" y2="8" />
          </pattern>
        </defs>
        <line className={styles.axis} x1={PAD.left} y1={y(0)} x2={WIDTH - PAD.right} y2={y(0)} />
        <line className={styles.grid} x1={PAD.left} y1={y(top)} x2={WIDTH - PAD.right} y2={y(top)} />
        <text className={styles.label} x={PAD.left - 6} y={y(0) + 4} textAnchor="end">
          0
        </text>
        <text className={styles.label} x={PAD.left - 6} y={y(top) + 4} textAnchor="end">
          {top}
        </text>
        {gaps.map((gap) => (
          <rect
            key={gap.from}
            className={styles.gap}
            x={x(gap.from)}
            y={PAD.top}
            width={Math.max(x(gap.to) - x(gap.from), 1)}
            height={HEIGHT - PAD.top - PAD.bottom}
            fill={`url(#${patternId})`}
          />
        ))}
        <path className={styles.line} d={path(history, x, y)} fill="none" />
        {history.points.map((point) => (
          <circle key={point.at} className={styles.point} cx={x(Date.parse(point.at))} cy={y(point.available ?? 0)} r="4" />
        ))}
        {widest !== null && x(widest.to) - x(widest.from) > 90 ? (
          <text className={styles.unknownLabel} x={(x(widest.from) + x(widest.to)) / 2} y={(PAD.top + HEIGHT - PAD.bottom) / 2} textAnchor="middle">
            Capacity unknown
          </text>
        ) : null}
        {ticks.map((time, index) => (
          <text key={time} className={styles.label} x={x(time)} y={HEIGHT - 8} textAnchor={index === 0 ? 'start' : index === ticks.length - 1 ? 'end' : 'middle'}>
            {clockTime(new Date(time).toISOString())}
          </text>
        ))}
      </svg>
      <details className={styles.details}>
        <summary>Show the reports as a table</summary>
        {history.points.length === 0 ? (
          <p className={styles.note}>No report in the last day.</p>
        ) : (
          <table className={styles.table}>
            <thead>
              <tr>
                <th scope="col">Reported</th>
                <th scope="col">{history.unitLabel}</th>
                <th scope="col">Status</th>
              </tr>
            </thead>
            <tbody>
              {history.points.map((point) => (
                <tr key={point.at}>
                  <td>{clockTime(point.at)}</td>
                  <td>{point.overBy === null ? (point.available ?? 'Not known') : `${point.overBy} over`}</td>
                  <td>{point.status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </details>
    </figure>
  );
}
