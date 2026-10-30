import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { HeatGrid } from './HeatGrid';

// Seven days by four bands. Thursday, 12:00 to 18:00 is the busiest, with 9.
const GRID = [
  [1, 2, 3, 0],
  [0, 1, 2, 1],
  [2, 2, 1, 0],
  [1, 0, 9, 2],
  [0, 1, 1, 1],
  [0, 0, 2, 0],
  [1, 1, 0, 0],
];

describe('HeatGrid', () => {
  it('renders 28 cells with their numbers, in a table that is the accessible form', () => {
    render(<HeatGrid grid={GRID} />);

    const table = screen.getByRole('table', { name: /by day and time/i });
    const cells = within(table).getAllByRole('cell');
    expect(cells).toHaveLength(28);
    expect(within(table).getByRole('cell', { name: '9' })).toBeInTheDocument();
  });

  it('announces the busiest cell in words', () => {
    render(<HeatGrid grid={GRID} />);

    expect(screen.getByText('Busiest: Thursday 12:00 to 18:00 (9)')).toBeInTheDocument();
  });

  it('passes vitest-axe', async () => {
    const { container } = render(<HeatGrid grid={GRID} />);

    expect(await runAxe(container)).toHaveNoViolations();
  });
});
