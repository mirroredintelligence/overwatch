import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { OVERVIEW_SHIFT_LEAD } from '@/test/fixtures/lead';
import { SystemCounts } from './SystemCounts';

describe('SystemCounts', () => {
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

  it('says how many services report today', () => {
    render(<SystemCounts counts={OVERVIEW_SHIFT_LEAD.counts} reportingToday={9} />);
    expect(screen.getByText('9 services reporting today')).toBeInTheDocument();
  });

  it('has no axe violations', async () => {
    const { container } = render(
      <SystemCounts counts={OVERVIEW_SHIFT_LEAD.counts} reportingToday={OVERVIEW_SHIFT_LEAD.reportingToday} />,
    );
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
