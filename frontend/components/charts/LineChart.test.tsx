import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { LineChart } from './LineChart';

const POINTS = [
  { label: '00:00', value: 1 },
  { label: '04:00', value: 2 },
  { label: '08:00', value: 3 },
  { label: '12:00', value: 5 },
  { label: '16:00', value: 3 },
  { label: '20:00', value: 2 },
  { label: '24:00', value: 1 },
];
const TABLE = { columns: ['Hour', 'Services limited or worse'], rows: POINTS.map((p) => [p.label, p.value]) };

function setup() {
  return render(
    <LineChart
      label="Services limited or worse by hour, peaking at 5 at 12:00"
      points={POINTS}
      threshold={{ value: 5, label: 'alert at 5' }}
      table={TABLE}
    />,
  );
}

describe('LineChart', () => {
  it('is an image that says the finding in words', () => {
    setup();
    expect(screen.getByRole('img', { name: 'Services limited or worse by hour, peaking at 5 at 12:00' })).toBeInTheDocument();
  });

  it('draws one polyline with a point per row', () => {
    const { container } = setup();
    const line = container.querySelector('polyline');
    expect(line).not.toBeNull();
    expect(line!.getAttribute('points')!.trim().split(/\s+/)).toHaveLength(POINTS.length);
  });

  it('starts the axis at zero and labels it', () => {
    const { container } = setup();
    const svg = container.querySelector('svg')!;
    expect(within(svg as unknown as HTMLElement).getByText('0')).toBeInTheDocument();
  });

  it('labels the peak with its number and marks it', () => {
    const { container } = setup();
    const peak = container.querySelector('[data-peak]');
    expect(peak).not.toBeNull();
    expect(peak!.textContent).toBe('5');
    expect(container.querySelector('circle')).not.toBeNull();
  });

  it('draws the threshold as a dashed line with its own words', () => {
    const { container } = setup();
    const line = container.querySelector('line[data-threshold]');
    expect(line).not.toBeNull();
    expect(line!.getAttribute('stroke-dasharray')).toBeTruthy();
    expect(screen.getByText('alert at 5')).toBeInTheDocument();
  });

  it('labels the start, the middle and the end of the time axis', () => {
    setup();
    const svg = screen.getByRole('img');
    expect(within(svg).getByText('00:00')).toBeInTheDocument();
    expect(within(svg).getAllByText('12:00').length).toBeGreaterThan(0);
    expect(within(svg).getByText('24:00')).toBeInTheDocument();
  });

  it('keeps the same rows in a table behind "Show as a table"', () => {
    setup();
    const button = screen.getByRole('button', { name: 'Show as a table' });
    fireEvent.click(button);
    expect(button).toHaveAttribute('aria-expanded', 'true');
    expect(within(screen.getByRole('table', { hidden: true })).getAllByRole('row', { hidden: true })).toHaveLength(POINTS.length + 1);
  });

  it('has no axe violations', async () => {
    const { container } = setup();
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
