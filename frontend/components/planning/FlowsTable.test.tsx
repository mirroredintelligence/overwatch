import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { FlowsTable } from './FlowsTable';

const FLOWS = [
  { bestFit: 'Falls team, Weymouth', state: 'full', wentTo: 'Community beds, Dorchester', count: 41, suppressed: false },
  { bestFit: 'Frailty ward, Bridport', state: 'closed', wentTo: 'Virtual ward', count: null, suppressed: true },
];

describe('FlowsTable', () => {
  it('shows fewer than 10 and no bar or share for a suppressed row', () => {
    const { container } = render(<FlowsTable flows={FLOWS} total={112} />);

    const table = screen.getByRole('table', { name: /where they went/i });
    const hidden = within(table).getByRole('row', { name: /Frailty ward, Bridport/ });
    expect(hidden).toHaveTextContent('fewer than 10');
    expect(hidden.querySelector('[data-bar]')).toBeNull();
    expect(container.querySelectorAll('[data-bar]')).toHaveLength(1);
  });

  it('shows the share of a shown row as text, of the referrals whose best fit was unavailable', () => {
    render(<FlowsTable flows={FLOWS} total={112} />);

    // 41 of 112 is 37%.
    expect(screen.getByText('37%')).toBeInTheDocument();
  });

  it('says why small counts are hidden', () => {
    render(<FlowsTable flows={FLOWS} total={112} />);

    expect(screen.getByText('Counts under 10 are not shown, to protect small groups.')).toBeInTheDocument();
  });

  it('passes vitest-axe', async () => {
    const { container } = render(<FlowsTable flows={FLOWS} total={112} />);

    expect(await runAxe(container)).toHaveNoViolations();
  });
});
