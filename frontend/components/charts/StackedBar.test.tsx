import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { StackedBar, type StackedSegment } from './StackedBar';

const SEGMENTS: StackedSegment[] = [
  { key: 'acc', label: 'Accepting', value: 52, glyph: '●', tone: 'primary', pattern: 'solid' },
  { key: 'lim', label: 'Limited', value: 22, glyph: '◐', tone: 'limited', pattern: 'solid' },
  { key: 'clo', label: 'Not accepting', value: 9, glyph: '■', tone: 'closed', pattern: 'solid' },
  { key: 'over', label: 'Over capacity', value: 6, glyph: '▲', tone: 'surge', pattern: 'hatch' },
  { key: 'unk', label: 'Not updated', value: 11, glyph: '◌', tone: 'unknown', pattern: 'dashed' },
  { key: 'oh', label: 'Out of hours', value: 0, tone: 'closed', pattern: 'solid' },
];
const TABLE = { columns: ['Status', 'Share of the week'], rows: SEGMENTS.map((s) => [s.label, `${s.value}%`]) };

function setup() {
  return render(
    <StackedBar
      label="Accepting 52%, limited 22%, not accepting 9%, over capacity 6%, not updated 11%"
      segments={SEGMENTS}
      unit="%"
      table={TABLE}
    />,
  );
}

describe('StackedBar', () => {
  it('is an image that says the shares in words', () => {
    setup();
    expect(screen.getByRole('img', { name: /Accepting 52%, limited 22%/ })).toBeInTheDocument();
  });

  it('splits one bar by value and leaves out a zero segment', () => {
    const { container } = setup();
    const parts = container.querySelectorAll<HTMLElement>('[data-segment]');
    expect(parts).toHaveLength(5);
    expect(JSON.parse(parts[0].dataset.css ?? '{}').flexGrow).toBe(52);
    expect(JSON.parse(parts[3].dataset.css ?? '{}').flexGrow).toBe(6);
  });

  it('gives each segment a pattern as well as a colour', () => {
    const { container } = setup();
    const patterns = Array.from(container.querySelectorAll('[data-segment]')).map((e) => e.getAttribute('data-pattern'));
    expect(patterns).toEqual(['solid', 'solid', 'solid', 'hatch', 'dashed']);
  });

  it('has a legend with glyph, word and number for every segment, zero included', () => {
    setup();
    const legend = screen.getByRole('list', { name: 'Legend' });
    const items = within(legend).getAllByRole('listitem');
    expect(items).toHaveLength(6);
    expect(items[0]).toHaveTextContent('● Accepting 52%');
    expect(items[3]).toHaveTextContent('▲ Over capacity 6%');
    expect(items[4]).toHaveTextContent('◌ Not updated 11%');
    expect(items[5]).toHaveTextContent('Out of hours 0%');
  });

  it('keeps the same rows in a table behind "Show as a table"', () => {
    setup();
    const button = screen.getByRole('button', { name: 'Show as a table' });
    fireEvent.click(button);
    expect(button).toHaveAttribute('aria-expanded', 'true');
    expect(within(screen.getByRole('table', { hidden: true })).getByText('Over capacity')).toBeInTheDocument();
  });

  it('has no axe violations', async () => {
    const { container } = setup();
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
