import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { Funnel } from './Funnel';

const STEPS = [
  { label: 'Invitation delivered', value: 100 },
  { label: 'Link opened', value: 82 },
  { label: 'Code verified', value: 71 },
  { label: 'PIN created', value: 41 },
];
const TABLE = { columns: ['Step', 'Share'], rows: STEPS.map((s) => [s.label, `${s.value}%`]) };

function setup(steps = STEPS) {
  return render(<Funnel label="Share who reach each step of set-up" steps={steps} unit="%" table={TABLE} />);
}

describe('Funnel', () => {
  it('is an image that says what it shows', () => {
    setup();
    expect(screen.getByRole('img', { name: /Share who reach each step of set-up/ })).toBeInTheDocument();
  });

  it('shows each step with its word and its number', () => {
    setup();
    const chart = screen.getByRole('img');
    for (const s of STEPS) {
      expect(within(chart).getByText(s.label)).toBeInTheDocument();
      expect(within(chart).getByText(`${s.value}%`)).toBeInTheDocument();
    }
  });

  it('starts every bar at zero: the width is the value', () => {
    const { container } = setup();
    const bars = container.querySelectorAll<HTMLElement>('[data-step-bar]');
    expect(bars).toHaveLength(4);
    expect(JSON.parse(bars[1].dataset.css ?? '{}').width).toBe('82%');
    expect(JSON.parse(bars[3].dataset.css ?? '{}').width).toBe('41%');
  });

  it('shows the drop from the step before', () => {
    setup();
    expect(screen.getByText('−18')).toBeInTheDocument();
    expect(screen.getByText('−11')).toBeInTheDocument();
  });

  it('hatches the one biggest drop and names it in words', () => {
    const { container } = setup();
    const hatched = container.querySelectorAll('[data-step-bar][data-biggest="true"]');
    expect(hatched).toHaveLength(1);
    expect(hatched[0]).toHaveAttribute('data-step', '3');
    expect(screen.getByText('−30 biggest')).toBeInTheDocument();
    expect(screen.getByText('Biggest drop: Code verified to PIN created, 30 points.')).toBeInTheDocument();
  });

  it('with no drop at all, hatches nothing', () => {
    const { container } = setup([
      { label: 'A', value: 50 },
      { label: 'B', value: 50 },
    ]);
    expect(container.querySelector('[data-biggest="true"]')).toBeNull();
    expect(screen.queryByText(/Biggest drop/)).toBeNull();
  });

  it('keeps the same rows in a table behind "Show as a table"', () => {
    setup();
    const button = screen.getByRole('button', { name: 'Show as a table' });
    fireEvent.click(button);
    expect(button).toHaveAttribute('aria-expanded', 'true');
    expect(within(screen.getByRole('table', { hidden: true })).getAllByRole('row', { hidden: true })).toHaveLength(5);
  });

  it('has no axe violations', async () => {
    const { container } = setup();
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
