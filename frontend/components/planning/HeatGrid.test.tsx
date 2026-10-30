import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { HeatGrid } from './HeatGrid';

// Seven days by four bands, as the back end sends them: a cell under 10 is null. Thursday, 12:00 to
// 18:00 is the busiest, with 12.
const GRID: (number | null)[][] = [
  [null, null, null, null],
  [null, null, 10, null],
  [null, null, null, null],
  [null, null, 12, null],
  [null, null, null, null],
  [null, null, null, null],
  [null, null, null, null],
];
const BUSIEST = { day: 3, band: 2, count: 12 };

describe('HeatGrid', () => {
  it('renders 28 cells in a table that is the accessible form, with fewer than 10 for a hidden cell and never a zero', () => {
    render(<HeatGrid grid={GRID} busiest={BUSIEST} />);

    const table = screen.getByRole('table', { name: /by day and time/i });
    const cells = within(table).getAllByRole('cell');
    expect(cells).toHaveLength(28);
    expect(within(table).getByRole('cell', { name: '12' })).toBeInTheDocument();
    expect(within(table).getAllByRole('cell', { name: 'fewer than 10' })).toHaveLength(26);
    expect(within(table).queryByRole('cell', { name: '0' })).toBeNull();
  });

  it('announces the busiest cell in words, from the back end', () => {
    render(<HeatGrid grid={GRID} busiest={BUSIEST} />);

    expect(screen.getByText('Busiest: Thursday 12:00 to 18:00 (12)')).toBeInTheDocument();
  });

  it('says no day or time reached 10 when there is no busiest cell', () => {
    render(<HeatGrid grid={GRID.map((row) => row.map(() => null))} busiest={null} />);

    expect(screen.getByText('No day or time had 10 or more unavailable referrals.')).toBeInTheDocument();
  });

  it('passes vitest-axe', async () => {
    const { container } = render(<HeatGrid grid={GRID} busiest={BUSIEST} />);

    expect(await runAxe(container)).toHaveNoViolations();
  });
});
