import { STATUS_LABELS } from '@/components/ui/StatusBadge';
import { londonDate, londonTime } from '@/lib/board/format';
import { WEEK_PRESSURES, WEEK_STATUSES, type NetworkWeek as Week, type Pressure, type WeekMeasure } from '@/lib/network/types';
import { addDays } from '@/lib/network/week';
import { rangeText } from './WeekSummary';
import styles from './NetworkWeek.module.css';

// The network's week (TEN-082, docs/design/network-ui.md, NetworkWeek; redesign board NWeek). Capacity-derived
// measures only: the hours the board was sampled, the share of capacity updates that were on time, the share of
// each status as one stacked bar, the hours at each pressure and the pressure over time as a 7 by 24 grid with a
// table behind it. A small group is not shown ("Not shown: fewer than 10."), a week made from too few
// organisations is withheld whole in its own card, and there is no breakdown by member. It is a history of what
// the board showed, read as figures, never as a live status (H-654).

const HIDDEN = 'Not shown: fewer than 10.';
const PRESSURE_WORDS: Record<Pressure, string> = { normal: 'Normal', watch: 'Watch', high: 'High' };
const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
const HOUR_MARKS = [0, 6, 12, 18];
const HOURS = Array.from({ length: 24 }, (_, hour) => hour);

// The bar and its key carry the shape of each status as a symbol; the symbol is drawn by CSS from data-symbol.
const STATUS_SYMBOLS: Record<(typeof WEEK_STATUSES)[number], string> = {
  accepting: '●',
  limited: '◐',
  'not-accepting': '■',
  'over-capacity': '▲',
  'not-updated': '◌',
  'out-of-hours': '',
};
// Out of hours is not a part of the bar: it is said on a line of its own.
const BAR_STATUSES = WEEK_STATUSES.filter((status) => status !== 'out-of-hours');

const shown = (measure: WeekMeasure): number | null => (measure.hidden || measure.value === null ? null : measure.value);
const hoursWord = (n: number) => `${n} ${n === 1 ? 'hour' : 'hours'}`;

const LONDON_PARTS = new Intl.DateTimeFormat('en-GB', {
  timeZone: 'Europe/London',
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  hourCycle: 'h23',
});

/** The day of the week (0 = the Monday the week starts) and the hour, in London, of one sampled hour. */
function cellOf(instant: string, weekStart: string): { day: number; hour: number } | null {
  const parts = Object.fromEntries(LONDON_PARTS.formatToParts(new Date(instant)).map((part) => [part.type, part.value]));
  const date = `${parts.year}-${parts.month}-${parts.day}`;
  const day = Math.round((Date.parse(`${date}T00:00:00Z`) - Date.parse(`${weekStart}T00:00:00Z`)) / 86_400_000);
  return day >= 0 && day < 7 ? { day, hour: Number(parts.hour) } : null;
}

function Figure({ value, label }: { value: string | null; label: string }) {
  return (
    <li className={styles.figure}>
      {value === null ? (
        <>
          <span className={styles.hidden}>{HIDDEN}</span>
          <span className={styles.figureLabel}>{label}</span>
        </>
      ) : (
        <>
          {/* Said as one phrase to a screen reader; the figure and its label are two lines to the eye. */}
          <span className={styles.srOnly}>{`${value} ${label}`}</span>
          <b className={styles.figureValue} aria-hidden="true">{value}</b>
          <span className={styles.figureLabel} aria-hidden="true">{label}</span>
        </>
      )}
    </li>
  );
}

// One stacked bar of the shares of the week. Its name says every share, so the bar is not colour alone.
function StatusBar({ week }: { week: Week }) {
  const parts = BAR_STATUSES.map((status) => ({ status, value: shown(week.statusShare[status]) }));
  const name = parts.map(({ status, value }) => `${STATUS_LABELS[status]} ${value === null ? 'not shown' : `${Math.round(value)}%`}`).join(', ');
  const drawn = parts.filter((part) => part.value !== null && part.value > 0);
  return (
    <>
      {drawn.length > 0 ? (
        <div role="img" aria-label={name} className={styles.bar}>
          {drawn.map(({ status, value }) => (
            <span key={status} data-status={status} data-css={JSON.stringify({ flexGrow: value ?? 0 })} />
          ))}
        </div>
      ) : null}
      <ul className={styles.key} aria-label="Share of services by status">
        {parts.map(({ status, value }) =>
          value === null ? (
            <li key={status} className={styles.keyItem}>
              <i data-status={status} aria-hidden="true" />
              <span>{STATUS_LABELS[status]}</span> <span>{HIDDEN}</span>
            </li>
          ) : (
            <li key={status} className={styles.keyItem} data-symbol={STATUS_SYMBOLS[status]}>
              <i data-status={status} aria-hidden="true" />
              {`${STATUS_LABELS[status]} ${Math.round(value)}%`}
            </li>
          ),
        )}
      </ul>
    </>
  );
}

// The 7 by 24 grid: the highest pressure of each hour the board was sampled. Normal is plain, watch is hatched,
// high is solid with a dark edge, an hour that was not sampled is empty: pattern as well as colour. Each hour
// is also in the table below, so the grid is a picture of it.
function PressureGrid({ week }: { week: Week }) {
  const byCell = new Map<string, Pressure>();
  for (const point of week.pressureOverTime) {
    const cell = cellOf(point.hour, week.weekStart);
    if (cell !== null) byCell.set(`${cell.day}-${cell.hour}`, point.pressure);
  }
  return (
    <div className={styles.grid} role="img" aria-label="Pressure for each hour of the week, by day and hour. Each hour is also in the table.">
      <div className={styles.gridRow}>
        <span />
        {HOUR_MARKS.map((hour) => (
          <span key={hour} className={styles.mark}>
            {String(hour).padStart(2, '0')}
          </span>
        ))}
      </div>
      {DAYS.map((name, day) => (
        <div key={name} className={styles.gridRow}>
          <span>{name}</span>
          {HOURS.map((hour) => (
            <i key={hour} data-day={day} data-hour={hour} data-pressure={byCell.get(`${day}-${hour}`) ?? 'none'} />
          ))}
        </div>
      ))}
    </div>
  );
}

export function NetworkWeek({ week, networkName }: { week: Week; networkName: string }) {
  const end = addDays(week.weekStart, 6);
  const hoursSampled = shown(week.hoursSampled);
  const onTime = shown(week.onTimePct);
  const outOfHours = shown(week.statusShare['out-of-hours']);
  return (
    <div className={styles.week}>
      <header className={styles.header}>
        <p className={styles.range}>{rangeText(week.weekStart, end)}</p>
        <h1 className={styles.title}>{`${networkName} this week`}</h1>
        <p className={styles.note}>This is what the network board showed, hour by hour. It is not a live status.</p>
      </header>

      {week.withheld ? (
        <section className={`${styles.card} ${styles.withheld}`} aria-labelledby="net-week-withheld">
          <h2 id="net-week-withheld" className={styles.eyebrow}>If too few organisations shared</h2>
          <p role="status" className={styles.withheldText}>
            This week is not shown. Too few organisations shared capacity for it to be shown without identifying one.
          </p>
        </section>
      ) : (
        <div className={styles.body}>
          <div className={styles.column}>
            <ul className={styles.figures} aria-label="Figures for the week">
              <Figure value={hoursSampled === null ? null : String(hoursSampled)} label={hoursSampled === 1 ? 'hour sampled' : 'hours sampled'} />
              <Figure value={onTime === null ? null : `${Math.round(onTime)}%`} label="capacity updates on time" />
            </ul>

            <section className={`${styles.card} ${styles.grow}`} aria-labelledby="net-week-status">
              <h2 id="net-week-status" className={styles.eyebrow}>Services by status, share of the week</h2>
              <StatusBar week={week} />
              <p className={styles.line}>{`Out of hours: ${outOfHours === null ? HIDDEN : `${Math.round(outOfHours)}%`}`}</p>
              <h2 className={`${styles.eyebrow} ${styles.gap}`}>Hours at each pressure</h2>
              <ul className={styles.levels} aria-label="Hours at each pressure">
                {WEEK_PRESSURES.map((level) => {
                  const hours = shown(week.pressureHours[level]);
                  return (
                    <li key={level} className={styles.level} data-pressure={level}>
                      {hours === null ? <span className={styles.hidden}>{HIDDEN}</span> : <b className={styles.levelValue}>{hoursWord(hours)}</b>}
                      <span>{PRESSURE_WORDS[level]}</span>
                    </li>
                  );
                })}
              </ul>
            </section>
          </div>

          <div className={styles.column}>
            <section className={styles.card} aria-labelledby="net-week-time">
              <h2 id="net-week-time" className={styles.eyebrow}>Pressure over time</h2>
              <PressureGrid week={week} />
              <ul className={styles.legend} aria-label="Pressure key">
                {(['normal', 'watch', 'high', 'none'] as const).map((level) => (
                  <li key={level} className={styles.keyItem}>
                    <i data-pressure={level} aria-hidden="true" />
                    <span>{level === 'none' ? 'Not sampled' : PRESSURE_WORDS[level]}</span>
                  </li>
                ))}
              </ul>
              <p className={styles.line}>The highest pressure of each hour the board was sampled. Each hour is also in the table.</p>
              {week.pressureOverTime.length > 0 ? (
                <details className={styles.table}>
                  <summary>Show as a table</summary>
                  <table>
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
          </div>
        </div>
      )}

      <p className={styles.footnote}>Capacity-derived measures only. There is no breakdown by member. {HIDDEN}</p>
    </div>
  );
}
