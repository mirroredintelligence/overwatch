import styles from '../console/Console.module.css';
import layout from './Planning.module.css';
import { StyledTd } from '@/components/ui/Styled';

// When the best fit was unavailable (W51, PlanningView artboard): the four bands of the day down the
// side and the seven days across, shaded by count, with the number in each cell. The table is the
// accessible form, and the busiest cell is also said in words. A cell under 10 is not a zero: it says
// "fewer than 10" and is shaded as the lightest step.

export const DAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'] as const;
export const BANDS = ['00:00 to 06:00', '06:00 to 12:00', '12:00 to 18:00', '18:00 to 24:00'] as const;

export function HeatGrid({ grid, busiest }: { grid: readonly (number | null)[][]; busiest: { day: number; band: number; count: number } | null }) {
  const max = busiest?.count ?? 0;
  return (
    <section aria-labelledby="heat-heading" className={styles.section}>
      <div>
        <h2 id="heat-heading" className={styles.heading}>When the best fit was unavailable</h2>
        <p className={styles.help}>Referrals by day and time of day</p>
      </div>
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
              <th scope="row">{band}</th>
              {DAYS.map((day, dayIndex) => {
                const count = grid[dayIndex]?.[bandIndex] ?? null;
                // The darkest step is the artboard's #6FB0D6 (55% of the primary): the number stays readable on it.
                const opacity = count === null || max === 0 ? 0.08 : 0.15 + (0.4 * count) / max;
                return (
                  <StyledTd key={day} css={{ background: `color-mix(in srgb, var(--c-primary) ${Math.round(opacity * 100)}%, transparent)` }}>
                    {count === null ? (
                      <>
                        <span aria-hidden="true">&lt;10</span>
                        <span className={layout.srOnly}>fewer than 10</span>
                      </>
                    ) : (
                      count
                    )}
                  </StyledTd>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
      <p className={styles.help}>
        {busiest === null
          ? 'No day or time had 10 or more unavailable referrals.'
          : `Busiest: ${DAYS[busiest.day] ?? ''} ${BANDS[busiest.band] ?? ''} (${busiest.count})`}
      </p>
    </section>
  );
}
