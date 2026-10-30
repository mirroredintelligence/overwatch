import styles from '../console/Console.module.css';

// When the best fit was unavailable (W51): days by bands, shaded by count, with the number in each
// cell. The table is the accessible form, and the busiest cell is also said in words.

export const DAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'] as const;
export const BANDS = ['00:00 to 06:00', '06:00 to 12:00', '12:00 to 18:00', '18:00 to 24:00'] as const;

export function HeatGrid({ grid, busiest }: { grid: readonly (number | null)[][]; busiest: { day: number; band: number; count: number } | null }) {
  const max = busiest?.count ?? 0;
  return (
    <section aria-labelledby="heat-heading">
      <h2 id="heat-heading" className={styles.heading}>When the best fit was unavailable</h2>
      <table className={styles.table} aria-label="Unavailable referrals by day and time">
        <thead>
          <tr>
            <th scope="col">Day</th>
            {BANDS.map((band) => (
              <th key={band} scope="col">{band}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {DAYS.map((day, dayIndex) => (
            <tr key={day}>
              <th scope="row">{day}</th>
              {BANDS.map((band, bandIndex) => {
                const count = grid[dayIndex]?.[bandIndex] ?? null;
                const opacity = count === null || max === 0 ? 0.08 : 0.15 + (0.85 * count) / max;
                return (
                  <td key={band} style={{ background: `color-mix(in srgb, var(--c-primary) ${Math.round(opacity * 100)}%, transparent)` }}>
                    {count === null ? 'fewer than 10' : count}
                  </td>
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
