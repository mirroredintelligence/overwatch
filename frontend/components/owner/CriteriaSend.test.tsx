import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { resetCriteriaRequests, seenCriteriaRequests } from '@/test/msw/handlers/criteria';
import { server } from '@/test/msw/server';
import type { CriteriaValues } from '@/lib/criteria/types';
import { CriteriaSend } from './CriteriaSend';

const SUBMIT = '/api/bff/criteria/s1/submit';
beforeEach(() => resetCriteriaRequests());
const posts = () => seenCriteriaRequests.filter((r) => r.method === 'POST' && r.path === SUBMIT);
const VALUES: CriteriaValues = { accepts: ['fall-no-injury'], excludes: [], ageMin: 16, ageMax: null, districts: ['DT1'] };

// The user-event tests here run slowly when the whole suite shares the machine; the budget is per file.
vi.setConfig({ testTimeout: 15_000 });

describe('CriteriaSend', () => {
  it('says in words that the author cannot approve, and offers the reason and the review period', async () => {
    render(<CriteriaSend serviceId="s1" currentVersion={2} changes={['Youngest age 65 to 60']} values={VALUES} />);
    expect(await screen.findByRole('heading', { level: 2, name: 'Send for second approval' })).toBeInTheDocument();
    expect(
      screen.getByText('A change to criteria needs a second person to approve it. You cannot approve your own change.'),
    ).toBeInTheDocument();
    expect(screen.getByText('Youngest age 65 to 60')).toBeInTheDocument();
    expect(screen.getByText('No patient information. Up to 200 characters.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '3 months' })).toHaveAttribute('aria-pressed', 'false');
    expect(screen.getByRole('button', { name: 'Send for second approval' })).toBeInTheDocument();
  });

  it('refuses to send without a reason or a review period, and sends nothing', async () => {
    const user = userEvent.setup();
    render(<CriteriaSend serviceId="s1" currentVersion={2} changes={[]} values={VALUES} />);
    await user.click(await screen.findByRole('button', { name: 'Send for second approval' }));
    expect(await screen.findByText('Enter why you are changing this')).toBeInTheDocument();
    expect(screen.getByText('Choose when to review again')).toBeInTheDocument();
    expect(posts()).toHaveLength(0);
  });

  it('sends the reason with the review period, then shows the waiting tracker with version 2 still live', async () => {
    const user = userEvent.setup();
    render(<CriteriaSend serviceId="s1" currentVersion={3} changes={['Youngest age 18 to 16']} values={VALUES} />);

    await user.type(await screen.findByLabelText('Why are you changing this?'), 'Younger patients can be seen');
    const period = within(screen.getByRole('group', { name: 'Review again in' })).getByRole('button', { name: '6 months' });
    await user.click(period);
    expect(period).toHaveAttribute('aria-pressed', 'true');
    await user.click(screen.getByRole('button', { name: 'Send for second approval' }));

    expect(await screen.findByRole('heading', { level: 2, name: 'Waiting for approval' })).toBeInTheDocument();
    await waitFor(() => expect(posts()).toHaveLength(1));
    expect(posts()[0]?.body).toMatchObject({ reason: 'Younger patients can be seen', reviewInMonths: 6, ageMin: 16 });

    const status = screen.getByRole('status');
    expect(within(status).getByText('Version 3 stays live until someone else approves version 4.')).toBeInTheDocument();
    expect(within(status).getByText(/^Sent by you at \d{2}:\d{2}$/)).toBeInTheDocument();
    expect(within(status).getByText('Waiting for a second approver')).toBeInTheDocument();
    expect(within(status).getByText('Live for advisors')).toBeInTheDocument();
    expect(await runAxe(status)).toHaveNoViolations();
  });

  it('keeps the form and says it was not sent when the back end refuses', async () => {
    const user = userEvent.setup();
    server.use(http.post(SUBMIT, () => HttpResponse.json({ code: 'boom' }, { status: 500 })));
    render(<CriteriaSend serviceId="s1" currentVersion={2} changes={[]} values={VALUES} />);

    await user.type(await screen.findByLabelText('Why are you changing this?'), 'Younger patients can be seen');
    await user.click(screen.getByRole('button', { name: '3 months' }));
    await user.click(screen.getByRole('button', { name: 'Send for second approval' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('The change was not sent. Check it and try again.');
    expect(screen.getByRole('heading', { level: 2, name: 'Send for second approval' })).toBeInTheDocument();
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
    expect(screen.getByLabelText('Why are you changing this?')).toHaveValue('Younger patients can be seen');
  });
});
