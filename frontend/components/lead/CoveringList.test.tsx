import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { OVERVIEW_SHIFT_LEAD } from '@/test/fixtures/lead';
import { CoveringList } from './CoveringList';

describe('CoveringList', () => {
  it('explains where reports go, in the words of the screen', () => {
    render(<CoveringList items={OVERVIEW_SHIFT_LEAD.covering} />);
    expect(screen.getByText('Reports go to a registered number. Change it for leave or cover.')).toBeInTheDocument();
  });

  it('shows a cover row with its end time, and a usual-contact row without one', () => {
    render(<CoveringList items={OVERVIEW_SHIFT_LEAD.covering} />);
    const rows = screen.getAllByRole('listitem');
    expect(rows[0]).toHaveTextContent('UCR East · number ending 4821 · cover until 20:00');
    expect(rows[1]).toHaveTextContent('Reablement · number ending 0377 · usual contact');
  });

  it('gives each row a Change number link to that service', () => {
    render(<CoveringList items={OVERVIEW_SHIFT_LEAD.covering} />);
    const [first] = screen.getAllByRole('listitem');
    const link = within(first).getByRole('link', { name: 'Change number' });
    expect(link).toHaveAttribute('href', '/lead/reporters/number?service=s-ucr-east');
  });

  it('has no axe violations', async () => {
    const { container } = render(<CoveringList items={OVERVIEW_SHIFT_LEAD.covering} />);
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
