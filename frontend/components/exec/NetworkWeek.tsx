import { STATUS_LABELS } from '@/components/ui/StatusBadge';
import { londonDate, londonTime } from '@/lib/board/format';
import { WEEK_PRESSURES, WEEK_STATUSES, type NetworkWeek as Week, type Pressure, type WeekMeasure } from '@/lib/network/types';
import { addDays } from '@/lib/network/week';
import { rangeText } from './WeekSummary';
import styles from '@/components/network/Network.module.css';

// The network's week (TEN-082, docs/design/network-ui.md, NetworkWeek). Capacity-derived measures only: the
// hours the board was sampled, the share of capacity updates that were on time, the share of each status,
// the hours at each pressure and the pressure over time. A small group is not shown ("Not shown: fewer than
// 10."), a week made from too few organisations is withheld whole, and there is no breakdown by member.
// It is a history of what the board showed, read as figures, never as a live status (H-654).

const HIDDEN = 'Not shown: fewer than 10.';
const PRESSURE_WORDS: Record<Pressure, string> = { normal: 'Normal', watch: 'Watch', high: 'High' };

function Measure({ measure, children }: { measure: WeekMeasure; children: (value: number) => string }) {
  return measure.hidden || measure.value === null ? <span>{HIDDEN}</span> : <>{children(measure.value)}</>;
}

export function NetworkWeek({ week, networkName }: { week: Week; networkName: string }) {
  const end = addDays(week.weekStart, 6);
  return (
    <div className={styles.week}>
      <h1 className={styles.title}>{`${networkName} this week`}</h1>
      <p>{rangeText(week.weekStart, end)}</p>
      <p className={styles.muted}>This is what the network board showed, hour by hour. It is not a live status.</p>

      {week.withheld ? (
        <p role="status">This week is not shown. Too few organisations shared capacity for it to be shown without identifying one.</p>
      ) : (
        <>
          <ul className={styles.list} aria-label="Figures for the week">
            <li className={styles.row}>
              <Measure measure={week.hoursSampled}>{(n) => `${n} ${n === 1 ? 'hour' : 'hours'} sampled`}</Measure>
            </li>
            <li className={styles.row}>
              <Measure measure={week.onTimePct}>{(n) => `${Math.round(n)}% capacity updates on time`}</Measure>
            </li>
          </ul>

          <section aria-labelledby="net-week-status">
            <h2 id="net-week-status" className={styles.rowTitle}>Services by status</h2>
            <ul className={styles.list} aria-label="Share of services by status">
              {WEEK_STATUSES.map((status) => {
                const measure = week.statusShare[status];
                return measure.hidden || measure.value === null ? (
                  <li key={status} className={styles.row}>
                    <span>{STATUS_LABELS[status]}</span> <span>{HIDDEN}</span>
                  </li>
                ) : (
                  <li key={status} className={styles.row}>{`${STATUS_LABELS[status]} ${Math.round(measure.value)}%`}</li>
                );
              })}
            </ul>
          </section>

          <section aria-labelledby="net-week-pressure">
            <h2 id="net-week-pressure" className={styles.rowTitle}>Pressure</h2>
            <ul className={styles.list} aria-label="Hours at each pressure">
              {WEEK_PRESSURES.map((level) => {
                const measure = week.pressureHours[level];
                return measure.hidden || measure.value === null ? (
                  <li key={level} className={styles.row}>
                    <span>{PRESSURE_WORDS[level]}</span> <span>{HIDDEN}</span>
                  </li>
                ) : (
                  <li key={level} className={styles.row}>{`${PRESSURE_WORDS[level]} ${measure.value} ${measure.value === 1 ? 'hour' : 'hours'}`}</li>
                );
              })}
            </ul>
            {week.pressureOverTime.length > 0 ? (
              <details>
                <summary>{`Pressure over time (${week.pressureOverTime.length} ${week.pressureOverTime.length === 1 ? 'hour' : 'hours'})`}</summary>
                <table className={styles.table}>
                  <caption>The highest pressure of each hour the board was sampled</caption>
                  <thead>
                    <tr>
                      <th scope="col">Hour</th>
                      <th scope="col">Pressure</th>
                    </tr>
                  </thead>
                  <tbody>
                    {week.pressureOverTime.map((point) => (
                      <tr key={point.hour}>
                        <td>{`${londonDate(point.hour)} ${londonTime(point.hour)}`}</td>
                        <td>{PRESSURE_WORDS[point.pressure]}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </details>
            ) : null}
          </section>
        </>
      )}

      <p className={styles.muted}>No per-member breakdown is shown.</p>
    </div>
  );
}
