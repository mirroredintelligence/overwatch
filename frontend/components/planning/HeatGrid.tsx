import layout from './Planning.module.css';

// When the best fit was unavailable (W51, PFlows artboard): the four bands of the day down the side and
// the seven days across, shaded in seven steps by count, with the number in each cell. The table is the
// accessible form, and the busiest cell is also said in words. A cell under 10 is not a zero: it reads
// "<10" (and "under 10" to a screen reader) on a plain cell, with no shade.

export const DAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'] as const;
export const BANDS = ['00:00 to 06:00', '06:00 to 12:00', '12:00 to 18:00', '18:00 to 24:00'] as const;

const STEPS = 7;

/** The shade step (0 lightest, 6 darkest) of a count against the largest count shown. */
function step(count: number, max: number): number {
  return max <= 0 ? 0 : Math.min(STEPS - 1, Math.floor((count / max) * STEPS));
}

export function HeatGrid({ grid, busiest }: { grid: readonly (number | null)[][]; busiest: { day: number; band: number; count: number } | null }) {
  const max = Math.max(busiest?.count ?? 0, ...grid.flat().map((count) => count ?? 0));
  return (
    <section aria-labelledby="heat-heading" className={layout.card}>
      <h2 id="heat-heading" className={layout.cardTitle}>When the best fit was unavailable</h2>
      <table className={layout.heat} aria-label="Unavailable referrals by day and time">
        <thead>
          <tr>
            <th scope="col">
              <span className={layout.srOnly}>Time of day</span>
            </th>
            {DAYS.map((day) => (
              <th key={day} scope="col">
                <span aria-hidden="true">{day.slice(0, 3)}</span>
                <span className={layout.srOnly}>{day}</span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {BANDS.map((band, bandIndex) => (
            <tr key={band}>
              <th scope="row">
                <span aria-hidden="true">{band.replace(' to ', '–').replaceAll(':00', '')}</span>
                <span className={layout.srOnly}>{band}</span>
              </th>
              {DAYS.map((day, dayIndex) => {
                const count = grid[dayIndex]?.[bandIndex] ?? null;
                return (
                  <td key={day} data-step={count === null ? 'none' : step(count, max)}>
                    {count === null ? (
                      <>
                        <span aria-hidden="true">&lt;10</span>
                        <span className={layout.srOnly}>under 10</span>
                      </>
                    ) : (
                      count
                    )}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
      <p className={layout.note}>
        {busiest === null
          ? 'No day or time had 10 or more unavailable referrals.'
          : `Busiest: ${DAYS[busiest.day] ?? ''} ${BANDS[busiest.band] ?? ''} (${busiest.count})`}
      </p>
      <p className={layout.note}>Every cell shows its count, so shade is never the only signal.</p>
    </section>
  );
}
