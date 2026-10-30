import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { CaseSummaryLine } from './CaseSummaryLine';

describe('CaseSummaryLine (W11)', () => {
  it('renders the age, postcode, needs and urgency on one line with an Edit link back to the case', () => {
    render(
      <CaseSummaryLine
        caseId="4821"
        ageBand="80+"
        postcode="DT4 8XX"
        needs={['fall-no-injury', 'frailty']}
        urgency="within-2-hrs"
      />,
    );

    expect(screen.getByText('80+ · DT4 8XX · Fall, Frailty · Within 2 hrs')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Edit' })).toHaveAttribute('href', '/advisor/case/4821');
  });

  it('leaves out what is not yet set', () => {
    render(<CaseSummaryLine caseId="4821" ageBand={null} postcode={null} needs={[]} urgency={null} />);

    expect(screen.queryByText(/·/)).toBeNull();
  });

  it('has no axe violations', async () => {
    const { container } = render(
      <CaseSummaryLine caseId="4821" ageBand="80+" postcode="DT4 8XX" needs={['frailty']} urgency="today" />,
    );
    expect((await runAxe(container)).violations).toEqual([]);
  });
});
