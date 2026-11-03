import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { OVERVIEW_SHIFT_LEAD } from '@/test/fixtures/lead';
import { SystemCounts } from './SystemCounts';

describe('SystemCounts', () => {
  it('is a section called System now', () => {
    render(<SystemCounts counts={OVERVIEW_SHIFT_LEAD.counts} reportingToday={OVERVIEW_SHIFT_LEAD.reportingToday} />);
    expect(screen.getByRole('heading', { level: 2, name: 'System now' })).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'System now' })).toBeInTheDocument();
  });

  it('shows each count with its word', () => {
    render(<SystemCounts counts={OVERVIEW_SHIFT_LEAD.counts} reportingToday={OVERVIEW_SHIFT_LEAD.reportingToday} />);
    const expected: [string, string][] = [
      ['Accepting', '4'],
      ['Limited', '2'],
      ['Not accepting', '1'],
      ['Over capacity', '1'],
      ['Not updated', '1'],
    ];
    for (const [word, count] of expected) {
      expect(screen.getByText(word).nextElementSibling).toHaveTextContent(count);
    }
  });

  it('lists the five states in the board order: accepting, limited, over capacity, not accepting, not updated', () => {
    render(<SystemCounts counts={OVERVIEW_SHIFT_LEAD.counts} reportingToday={OVERVIEW_SHIFT_LEAD.reportingToday} />);
    const words = screen.getAllByRole('term').map((term) => term.textContent);
    expect(words).toEqual(['Accepting', 'Limited', 'Over capacity', 'Not accepting', 'Not updated']);
  });

  it('gives each state its own shape beside the word, so colour is not the only sign', () => {
    render(<SystemCounts counts={OVERVIEW_SHIFT_LEAD.counts} reportingToday={OVERVIEW_SHIFT_LEAD.reportingToday} />);
    const shapes: [string, string][] = [
      ['Accepting', 'circle'],
      ['Limited', 'square'],
      ['Over capacity', 'diamond'],
      ['Not accepting', 'dark-circle'],
      ['Not updated', 'dashed-circle'],
    ];
    for (const [word, shape] of shapes) {
      const term = screen.getByText(word);
      const mark = term.querySelector('[data-shape]');
      expect(mark, word).not.toBeNull();
      expect(mark).toHaveAttribute('data-shape', shape);
      expect(mark).toHaveAttribute('aria-hidden', 'true');
    }
  });

  it('shows a zero as a zero', () => {
    render(<SystemCounts counts={{ ...OVERVIEW_SHIFT_LEAD.counts, overCapacity: 0 }} reportingToday={9} />);
    expect(screen.getByText('Over capacity').nextElementSibling).toHaveTextContent('0');
  });

  it('says how many services report today', () => {
    render(<SystemCounts counts={OVERVIEW_SHIFT_LEAD.counts} reportingToday={9} />);
    expect(screen.getByText('9 services reporting today')).toBeInTheDocument();
  });

  it('says one service in the singular', () => {
    render(<SystemCounts counts={OVERVIEW_SHIFT_LEAD.counts} reportingToday={1} />);
    expect(screen.getByText('1 service reporting today')).toBeInTheDocument();
  });

  it('keeps the counts in one list of terms and figures', () => {
    render(<SystemCounts counts={OVERVIEW_SHIFT_LEAD.counts} reportingToday={9} />);
    const section = screen.getByRole('region', { name: 'System now' });
    expect(within(section).getAllByRole('definition')).toHaveLength(5);
  });

  it('has no axe violations', async () => {
    const { container } = render(
      <SystemCounts counts={OVERVIEW_SHIFT_LEAD.counts} reportingToday={OVERVIEW_SHIFT_LEAD.reportingToday} />,
    );
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
