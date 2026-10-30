import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { CRITERIA_OVERVIEW_WAITING } from '@/test/fixtures/criteria';
import { http, HttpResponse } from 'msw';
import { server } from '@/test/msw/server';
import { CriteriaOverview } from './CriteriaOverview';
import { CRITERIA_OVERVIEW } from '@/test/fixtures/criteria';
import userEvent from '@testing-library/user-event';

describe('CriteriaOverview', () => {
  it('shows the version, its review date, the accepts and does-not-accept lists, and the warning', async () => {
    const { container } = render(<CriteriaOverview serviceId="s1" />);
    expect(await screen.findByRole('heading', { level: 1, name: 'UCR West criteria' })).toBeInTheDocument();
    expect(screen.getByText('Version 3 · review by 12 Dec')).toBeInTheDocument();
    expect(screen.getByText('Accepts: Fall, no injury, Frailty, age 18+')).toBeInTheDocument();
    expect(screen.getByText('Does not accept: Suspected fracture, Head injury on anticoagulants')).toBeInTheDocument();
    expect(screen.getByText('Advisors rely on these. If they are out of date, advisors see a flag on your service.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Still right' })).toHaveAttribute('data-el', 'OWN-CRIT-STILLRIGHT-BTN');
    expect(screen.getByRole('button', { name: 'Change' })).toHaveAttribute('data-el', 'OWN-CRIT-CHANGE-BTN');
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('says advisors still see the current version while a new one waits for approval', async () => {
    server.use(http.get('/api/bff/criteria/:serviceId', () => HttpResponse.json(CRITERIA_OVERVIEW_WAITING)));
    render(<CriteriaOverview serviceId="s1" />);
    expect(await screen.findByText('Version 4 is waiting for approval. Advisors still see version 3.')).toBeInTheDocument();
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

    render(<CriteriaOverview serviceId="s1" />);
    expect(await screen.findByRole('heading', { level: 1, name: 'UCR West criteria' })).toBeInTheDocument();
    expect(screen.queryByText(/Criteria not reviewed since/)).not.toBeInTheDocument();
  });
});
