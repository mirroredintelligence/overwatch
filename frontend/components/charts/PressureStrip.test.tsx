import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { PressureStrip, type PressureLevel } from './PressureStrip';

const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
function level(day: number, hour: number): PressureLevel {
  if (day === 3 && hour >= 13 && hour <= 15) return 'high';
  if (day === 1 && hour === 12) return 'watch';
  if (day === 6 && hour === 5) return 'none';
  return 'normal';
}
const ROWS = DAYS.map((label, d) => ({ label, levels: Array.from({ length: 24 }, (_, h) => level(d, h)) }));
const TABLE = { columns: ['Day', 'Hours at watch', 'Hours at high'], rows: DAYS.map((d) => [d, 0, 0]) };

function setup() {
  return render(<PressureStrip label="Pressure by hour, highest on Thursday from 13:00 to 15:00" rows={ROWS} table={TABLE} />);
}

describe('PressureStrip', () => {
  it('is an image that says the finding in words', () => {
    setup();
    expect(screen.getByRole('img', { name: /highest on Thursday from 13:00 to 15:00/ })).toBeInTheDocument();
  });

  it('is a grid of 7 days by 24 hours', () => {
    const { container } = setup();
    expect(container.querySelectorAll('[data-row]')).toHaveLength(7);
    expect(container.querySelectorAll('[data-cell]')).toHaveLength(168);
  });

  it('labels each day and the hours 00, 06, 12 and 18', () => {
    setup();
    const chart = screen.getByRole('img');
    for (const d of DAYS) expect(within(chart).getByText(d)).toBeInTheDocument();
    for (const h of ['00', '06', '12', '18']) expect(within(chart).getByText(h)).toBeInTheDocument();
  });

  it('marks each level by its own data attribute so the style is a pattern, not a colour alone', () => {
    const { container } = setup();
    expect(container.querySelectorAll('[data-cell][data-level="high"]')).toHaveLength(3);
    expect(container.querySelectorAll('[data-cell][data-level="watch"]')).toHaveLength(1);
    expect(container.querySelectorAll('[data-cell][data-level="none"]')).toHaveLength(1);
  });

  it('has a legend with a word for every level', () => {
    setup();
    const legend = screen.getByRole('list', { name: 'Legend' });
    expect(within(legend).getByText('Normal')).toBeInTheDocument();
    expect(within(legend).getByText('Watch')).toBeInTheDocument();
    expect(within(legend).getByText('High')).toBeInTheDocument();
    expect(within(legend).getByText('Not sampled')).toBeInTheDocument();
  });

  it('keeps the same rows in a table behind "Show as a table"', () => {
    setup();
    const button = screen.getByRole('button', { name: 'Show as a table' });
    fireEvent.click(button);
    expect(button).toHaveAttribute('aria-expanded', 'true');
    expect(within(screen.getByRole('table', { hidden: true })).getAllByRole('row', { hidden: true })).toHaveLength(8);
  });

  it('has no axe violations', async () => {
    const { container } = setup();
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
