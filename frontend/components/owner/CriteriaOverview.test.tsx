import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { CRITERIA_OVERVIEW_WAITING } from '@/test/fixtures/criteria';
import { http, HttpResponse } from 'msw';
import { handlers } from '@/test/msw/handlers';
import { server } from '@/test/msw/server';
import { CriteriaOverview } from './CriteriaOverview';
import { CRITERIA_OVERVIEW } from '@/test/fixtures/criteria';
import { shortDate } from '@/lib/criteria/model';
import userEvent from '@testing-library/user-event';

// The user-event tests here run slowly when the whole suite shares the machine; the budget is per file.
vi.setConfig({ testTimeout: 15_000 });

/** A review date some days from today, as the API sends it (YYYY-MM-DD, on the local calendar). */
function isoDaysFromToday(days: number): string {
  const date = new Date();
  date.setDate(date.getDate() + days);
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

describe('CriteriaOverview', () => {
  it('shows the version, its review date, the accepts and does-not-accept lists, and the board wording', async () => {
    const { container } = render(<CriteriaOverview serviceId="s1" />);
    expect(await screen.findByRole('heading', { level: 1, name: 'UCR West criteria' })).toBeInTheDocument();
    expect(screen.getByText('Version 3 · review by 12 Dec')).toBeInTheDocument();
    expect(screen.getByText('Accepts: Fall, no injury, Frailty, age 18+')).toBeInTheDocument();
    expect(screen.getByText('Does not accept: Suspected fracture, Head injury on anticoagulants')).toBeInTheDocument();
    expect(
      screen.getByText('Advisors rely on these. They are the rules that decide whether a patient is offered to your service.'),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Still right' })).toHaveAttribute('data-el', 'OWN-CRIT-STILLRIGHT-BTN');
    expect(screen.getByRole('button', { name: 'Change them' })).toHaveAttribute('data-el', 'OWN-CRIT-CHANGE-BTN');
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('offers See the history as a link to the history page, after the two decisions', async () => {
    render(<CriteriaOverview serviceId="s1" />);
    expect(await screen.findByRole('heading', { level: 1, name: 'UCR West criteria' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'See the history' })).toHaveAttribute('href', '/criteria/s1/history');
    expect(screen.queryByRole('button', { name: 'Change' })).not.toBeInTheDocument();
  });

  it('moves the flow to Confirm from Still right, and to the change step from Change them', async () => {
    const user = userEvent.setup();
    const onNext = vi.fn();
    render(<CriteriaOverview serviceId="s1" onNext={onNext} />);
    await user.click(await screen.findByRole('button', { name: 'Still right' }));
    expect(onNext).toHaveBeenLastCalledWith('confirm');
    await user.click(screen.getByRole('button', { name: 'Change them' }));
    expect(onNext).toHaveBeenLastCalledWith('edit');
  });

  it('says advisors still see the current version while a new one waits for approval', async () => {
    server.use(http.get('/api/bff/criteria/:serviceId', () => HttpResponse.json(CRITERIA_OVERVIEW_WAITING)));
    render(<CriteriaOverview serviceId="s1" />);
    expect(await screen.findByText('Version 4 is waiting for approval. Advisors still see version 3.')).toBeInTheDocument();
  });

  it('shows the review-due notice, with the days left, when the review is within 30 days', async () => {
    const reviewBy = isoDaysFromToday(7);
    server.use(
      http.get('/api/bff/criteria/:serviceId', () =>
        HttpResponse.json({ ...CRITERIA_OVERVIEW, current: { ...CRITERIA_OVERVIEW.current, reviewBy } }),
      ),
    );
    const { container, unmount } = render(<CriteriaOverview serviceId="s1" />);
    expect(await screen.findByText('Criteria review due in 7 days')).toBeInTheDocument();
    expect(
      screen.getByText(
        `Due ${shortDate(reviewBy)}. Confirm or update in about two minutes. If they are out of date, advisors see a flag on your service.`,
      ),
    ).toBeInTheDocument();
    expect(await runAxe(container)).toHaveNoViolations();
    unmount();

    server.resetHandlers(...handlers);
    render(<CriteriaOverview serviceId="s1" />);
    expect(await screen.findByRole('heading', { level: 1, name: 'UCR West criteria' })).toBeInTheDocument();
    expect(screen.getByText('Version 3 · review by 12 Dec')).toBeInTheDocument();
    expect(screen.queryByText(/Criteria review due in/)).not.toBeInTheDocument();
  });

  it('does not show the review-due notice while the review is more than 30 days away', async () => {
    server.use(
      http.get('/api/bff/criteria/:serviceId', () =>
        HttpResponse.json({ ...CRITERIA_OVERVIEW, current: { ...CRITERIA_OVERVIEW.current, reviewBy: isoDaysFromToday(45) } }),
      ),
    );
    render(<CriteriaOverview serviceId="s1" />);
    expect(await screen.findByRole('heading', { level: 1, name: 'UCR West criteria' })).toBeInTheDocument();
    expect(screen.queryByText(/Criteria review due in/)).not.toBeInTheDocument();
  });

  it('shows the overdue notice, with the shift lead to ask, only when the review date has passed', async () => {
    const user = userEvent.setup();
    server.use(
      http.get('/api/bff/criteria/:serviceId', () =>
        HttpResponse.json({ ...CRITERIA_OVERVIEW, overdueSince: '2026-09-12', shiftLead: { role: 'Duty manager', phone: '01202 000 333' } }),
      ),
    );
    const { unmount } = render(<CriteriaOverview serviceId="s1" />);
    expect(await screen.findByRole('heading', { name: 'Criteria not reviewed since 12 Sep' })).toBeInTheDocument();
    expect(screen.getByText('Advisors see a flag on UCR West: “criteria not reviewed”.')).toBeInTheDocument();
    expect(screen.getByText('Not your service any more? Ask the shift lead to change the owner.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Review now' })).toHaveAttribute('data-el', 'OWN-OVERDUE-REVIEW-BTN');
    await user.click(screen.getByRole('button', { name: 'Ask to change the owner' }));
    expect(screen.getByText('Shift lead: Duty manager, 01202 000 333. No message is sent.')).toBeInTheDocument();
    unmount();

    server.resetHandlers(...handlers);
    render(<CriteriaOverview serviceId="s1" />);
    expect(await screen.findByRole('heading', { level: 1, name: 'UCR West criteria' })).toBeInTheDocument();
    expect(screen.queryByText(/Criteria not reviewed since/)).not.toBeInTheDocument();
  });
});
