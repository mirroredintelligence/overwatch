import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { resetCsrfCache } from '@/lib/advisor/browser';
import { runAxe } from '@/test/a11y';
import { byEl } from '@/test/el';
import { resetSeenAdvisorRequests } from '@/test/msw/handlers/advisor';
import { FinishScreen } from './FinishScreen';

vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn() }) }));

beforeEach(() => {
  resetCsrfCache();
  resetSeenAdvisorRequests();
});

describe('FinishScreen (W15)', () => {
  it('after "Save outcome" shows "Call closed", what was kept and what was cleared, and the postcode is gone', async () => {
    const user = userEvent.setup();
    render(<FinishScreen caseId="4821" preselect={null} />);

    expect(await screen.findByText('DT4 8XX')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Accepted and booked' }));
    await user.click(byEl('ADV-FIN-SAVE-BTN'));

    expect(await screen.findByRole('heading', { name: 'Call closed' })).toBeInTheDocument();
    expect(screen.getByText('Case closed')).toBeInTheDocument();
    expect(screen.getByText('Case 4821 is saved. The postcode has been cleared from this screen.')).toBeInTheDocument();
    expect(screen.getByText('Need category, age band, urgency, scores, destination, outcome, times, and what the board showed.')).toBeInTheDocument();
    expect(screen.getByText('Retention periods are for IG to set.')).toBeInTheDocument();
    expect(document.body.textContent).not.toContain('DT4 8XX');
    expect(screen.queryByRole('button', { name: 'Copy summary' })).toBeNull();
  });

  it('"Start next call" goes to the advisor home', async () => {
    const user = userEvent.setup();
    render(<FinishScreen caseId="4821" preselect={null} />);
    await user.click(screen.getByRole('button', { name: 'Accepted and booked' }));
    await user.click(byEl('ADV-FIN-SAVE-BTN'));

    expect(await screen.findByRole('link', { name: 'Start next call' })).toHaveAttribute('href', '/advisor');
  });

  it('has no axe violations in the form state and the closed state', async () => {
    const user = userEvent.setup();
    const { container } = render(<FinishScreen caseId="4821" preselect={null} />);
    await screen.findByText('DT4 8XX');
    expect((await runAxe(container)).violations).toEqual([]);

    await user.click(byEl('ADV-FIN-OUTCOME-DECLINED'));
    await user.click(byEl('ADV-FIN-SAVE-BTN'));
    await screen.findByRole('heading', { name: 'Call closed' });
    expect((await runAxe(container)).violations).toEqual([]);
  }, 30_000);
});
