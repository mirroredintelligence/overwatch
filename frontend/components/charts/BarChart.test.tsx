import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { BarChart } from './BarChart';

const BARS = [
  { label: 'Mon', value: 2 },
  { label: 'Tue', value: 3 },
  { label: 'Wed', value: 5, flagged: true },
  { label: 'Thu', value: 4 },
];
const TABLE = {
  columns: ['Day', 'Services limited or worse', 'At alert level'],
  rows: [
    ['Monday', 2, 'No'],
    ['Tuesday', 3, 'No'],
    ['Wednesday', 5, 'Yes'],
    ['Thursday', 4, 'No'],
  ],
};

function setup() {
  return render(
    <BarChart
      label="Services limited or worse by day, Wednesday at the alert level with 5"
      bars={BARS}
      threshold={{ value: 5, label: '5 or more raises an alert' }}
      table={TABLE}
    />,
  );
}

describe('BarChart', () => {
  it('is an image that says the finding in words', () => {
    setup();
    expect(screen.getByRole('img', { name: /Wednesday at the alert level with 5/ })).toBeInTheDocument();
  });

  it('puts the number and the label on every bar', () => {
    setup();
    const chart = screen.getByRole('img');
    for (const b of BARS) {
      expect(within(chart).getByText(String(b.value))).toBeInTheDocument();
      expect(within(chart).getByText(b.label)).toBeInTheDocument();
    }
  });

  it('draws the axis from zero: the bar height is its share of a scale above the biggest value', () => {
    const { container } = setup();
    const bars = container.querySelectorAll<HTMLElement>('[data-bar]');
    expect(bars).toHaveLength(4);
    // max = 5 + 1 headroom = 6, as the board
    expect(bars[0].style.getPropertyValue('--share')).toBe(String(2 / 6));
    expect(bars[2].style.getPropertyValue('--share')).toBe(String(5 / 6));
  });

  it('names the threshold line in words', () => {
    const { container } = setup();
    expect(screen.getByText('5 or more raises an alert')).toBeInTheDocument();
    expect(container.querySelector('[data-threshold]')).not.toBeNull();
  });

  it('marks the flagged bar in words, not colour alone', () => {
    const { container } = setup();
    expect(container.querySelector('[data-bar][data-flagged="true"]')).not.toBeNull();
    expect(screen.getByText('at the alert level')).toBeInTheDocument();
    expect(container.querySelectorAll('[data-bar][data-flagged="true"]')).toHaveLength(1);
  });

  it('keeps the same rows in a table behind "Show as a table"', () => {
    setup();
    const button = screen.getByRole('button', { name: 'Show as a table' });
    expect(button).toHaveAttribute('aria-expanded', 'false');
    fireEvent.click(button);
    expect(button).toHaveAttribute('aria-expanded', 'true');
    const table = screen.getByRole('table', { hidden: true });
    expect(within(table).getByText('Wednesday')).toBeInTheDocument();
    expect(within(table).getAllByRole('row', { hidden: true })).toHaveLength(5);
  });

  it('has no axe violations', async () => {
    const { container } = setup();
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
