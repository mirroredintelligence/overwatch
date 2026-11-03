import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { OVERVIEW_SHIFT_LEAD } from '@/test/fixtures/lead';
import { CoveringList } from './CoveringList';

describe('CoveringList', () => {
  it('is a section called Covering today', () => {
    render(<CoveringList items={OVERVIEW_SHIFT_LEAD.covering} />);
    expect(screen.getByRole('heading', { level: 2, name: 'Covering today' })).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Covering today' })).toBeInTheDocument();
  });

  it('explains where reports go, in the words of the screen', () => {
    render(<CoveringList items={OVERVIEW_SHIFT_LEAD.covering} />);
    expect(screen.getByText('Reports go to a registered number. Change it for leave or cover.')).toBeInTheDocument();
  });

  it('shows a cover row with its end time, and a usual-contact row without one', () => {
    render(<CoveringList items={OVERVIEW_SHIFT_LEAD.covering} />);
    const rows = screen.getAllByRole('listitem');
    expect(within(rows[0]).getByText('UCR East')).toBeInTheDocument();
    expect(rows[0]).toHaveTextContent('ending 4821 · cover until 20:00');
    expect(within(rows[1]).getByText('Reablement')).toBeInTheDocument();
    expect(rows[1]).toHaveTextContent('ending 0377 · usual contact');
  });

  it('gives each row a Change link to that service, named for the service', () => {
    render(<CoveringList items={OVERVIEW_SHIFT_LEAD.covering} />);
    const [first] = screen.getAllByRole('listitem');
    const link = within(first).getByRole('link', { name: 'Change number for UCR East' });
    expect(link).toHaveTextContent('Change');
    expect(link).toHaveAttribute('href', '/lead/reporters/number?service=s-ucr-east');
  });

  it('says that no one is covering when there is nothing to list', () => {
    render(<CoveringList items={[]} />);
    expect(
      screen.getByText('No one is covering for anyone. Every service reports to its usual contact.'),
    ).toBeInTheDocument();
    expect(screen.queryByRole('list')).not.toBeInTheDocument();
  });

  it('has no axe violations', async () => {
    const { container } = render(<CoveringList items={OVERVIEW_SHIFT_LEAD.covering} />);
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
