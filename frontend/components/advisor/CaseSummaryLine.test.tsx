import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { CaseSummaryLine } from './CaseSummaryLine';

describe('CaseSummaryLine (W11, the pinned patient card)', () => {
  it('is a card named This patient with the age and postcode large, one chip per need and the urgency', () => {
    render(
      <CaseSummaryLine
        caseId="4821"
        ageBand="80+"
        postcode="DT4 8XX"
        needs={['fall-no-injury', 'frailty']}
        urgency="within-2-hrs"
      />,
    );

    const card = screen.getByRole('region', { name: 'This patient' });
    expect(card).toHaveAttribute('data-el', 'ADV-CASE-SUMMARY');
    expect(within(card).getByText('80+ · DT4 8XX')).toBeInTheDocument();
    const chips = within(within(card).getByRole('list', { name: 'Needs and urgency' })).getAllByRole('listitem');
    expect(chips.map((chip) => chip.textContent)).toEqual(['Fall, no injury', 'Frailty', 'Within 2 hrs']);
  });

  it('has an Edit needs link back to the case', () => {
    render(<CaseSummaryLine caseId="4821" ageBand="80+" postcode="DT4 8XX" needs={['frailty']} urgency="today" />);

    const edit = screen.getByRole('link', { name: 'Edit needs' });
    expect(edit).toHaveAttribute('href', '/advisor/case/4821');
    expect(edit).toHaveAttribute('data-el', 'ADV-CASE-SUMMARY-EDIT');
  });

  it('shows the scores the referrer gave, and nothing when there are none', () => {
    const { rerender } = render(
      <CaseSummaryLine
        caseId="4821"
        ageBand="80+"
        postcode="DT4 8XX"
        needs={[]}
        urgency={null}
        scores={[
          { method: 'news2', value: 2 },
          { method: 'cfs', value: 6 },
        ]}
      />,
    );
    expect(screen.getByText('NEWS2 2 · Frailty scale 6 · Moderately frail')).toBeInTheDocument();

    rerender(<CaseSummaryLine caseId="4821" ageBand="80+" postcode="DT4 8XX" needs={[]} urgency={null} scores={[]} />);
    expect(screen.queryByText(/NEWS2/)).toBeNull();
  });

  it('leaves out what is not yet set', () => {
    render(<CaseSummaryLine caseId="4821" ageBand={null} postcode={null} needs={[]} urgency={null} />);

    expect(screen.queryByText(/·/)).toBeNull();
    expect(screen.queryByRole('list')).toBeNull();
    expect(screen.getByRole('link', { name: 'Edit needs' })).toBeInTheDocument();
  });

  it('shows the age alone when the postcode is not set', () => {
    render(<CaseSummaryLine caseId="4821" ageBand="65-79" postcode={null} needs={[]} urgency="planned" />);

    expect(screen.getByText('65 to 79')).toBeInTheDocument();
  });

  it('has no axe violations', async () => {
    const { container } = render(
      <CaseSummaryLine caseId="4821" ageBand="80+" postcode="DT4 8XX" needs={['frailty']} urgency="today" />,
    );
    expect((await runAxe(container)).violations).toEqual([]);
  });
});
