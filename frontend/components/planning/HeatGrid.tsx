import styles from '../console/Console.module.css';

// When the best fit was unavailable (W51): days by bands, shaded by count, with the number in each
// cell. The table is the accessible form, and the busiest cell is also said in words.

export const DAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'] as const;
export const BANDS = ['00:00 to 06:00', '06:00 to 12:00', '12:00 to 18:00', '18:00 to 24:00'] as const;

export function busiestOf(grid: readonly number[][]): { day: string; band: string; count: number } | null {
  let best: { day: string; band: string; count: number } | null = null;
  for (let dayIndex = 0; dayIndex < grid.length; dayIndex += 1) {
    const row = grid[dayIndex] ?? [];
    for (let bandIndex = 0; bandIndex < row.length; bandIndex += 1) {
      const count = row[bandIndex] ?? 0;
      const day = DAYS[dayIndex];
      const band = BANDS[bandIndex];
      if (day !== undefined && band !== undefined && (best === null || count > best.count)) {
        best = { day, band, count };
      }
    }
  }
  return best !== null && best.count > 0 ? best : null;
}

export function HeatGrid({ grid }: { grid: readonly number[][] }) {
  const busiest = busiestOf(grid);
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
                const count = grid[dayIndex]?.[bandIndex] ?? 0;
                const opacity = max > 0 ? 0.15 + (0.85 * count) / max : 0.15;
                return (
                  <td key={band} style={{ background: `color-mix(in srgb, var(--c-primary) ${Math.round(opacity * 100)}%, transparent)` }}>
                    {count}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
      <p className={styles.help}>
        {busiest === null
          ? 'No unavailable referrals in this period.'
          : `Busiest: ${busiest.day} ${busiest.band} (${busiest.count})`}
      </p>
    </section>
  );
}
