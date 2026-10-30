import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { PENDING_CHANGE, PENDING_REGISTRATION } from '@/test/fixtures/criteria';
import { resetCriteriaRequests, seenCriteriaRequests } from '@/test/msw/handlers/criteria';
import { server } from '@/test/msw/server';
import { CriteriaApproval } from './CriteriaApproval';

const DECISION = '/api/bff/criteria/s1/pending/decision';
beforeEach(() => resetCriteriaRequests());
const posts = () => seenCriteriaRequests.filter((r) => r.method === 'POST' && r.path === DECISION);

function pendingWith(body: unknown, status = 200) {
  server.use(http.get('/api/bff/criteria/:serviceId/pending', () => HttpResponse.json(body as Record<string, unknown>, { status })));
}

// The user-event tests here run slowly when the whole suite shares the machine; the budget is per file.
vi.setConfig({ testTimeout: 15_000 });

describe('CriteriaApproval', () => {
  it('shows what changed and the reason, and approves on "Yes, approve"', async () => {
    const user = userEvent.setup();
    const { container } = render(<CriteriaApproval serviceId="s1" />);
    expect(await screen.findByRole('heading', { level: 1, name: 'Second approval · UCR West' })).toBeInTheDocument();
    expect(screen.getByText('Youngest age 18 to 16')).toBeInTheDocument();
    expect(screen.getByText('Reason from Criteria owner: Younger patients can be seen')).toBeInTheDocument();
    expect(screen.getByText('Safe for advisors to rely on?')).toBeInTheDocument();
    expect(screen.getByText('Advisors see the new version only after you publish. The old version stays in the audit record.')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Yes, approve' }));
    expect(await screen.findByText('Approved. Advisors now see version 4.')).toBeInTheDocument();
    await waitFor(() => expect(posts()).toHaveLength(1));
    expect(posts()[0]?.body).toEqual({ decision: 'approve' });
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('asks for a note before a send back, then sends it', async () => {
    const user = userEvent.setup();
    render(<CriteriaApproval serviceId="s1" />);
    await user.click(await screen.findByRole('button', { name: 'Send back' }));
    expect(await screen.findByText('Enter a note for the criteria owner')).toBeInTheDocument();
    expect(posts()).toHaveLength(0);

    await user.type(screen.getByLabelText('Note (if sending back)'), 'Keep the age at 18 until the review.');
    await user.click(screen.getByRole('button', { name: 'Send back' }));
    await waitFor(() => expect(posts()).toHaveLength(1));
    expect(posts()[0]?.body).toEqual({ decision: 'send-back', note: 'Keep the age at 18 until the review.' });
  });

  it('hides both buttons from the author, and says another clinical lead must approve', async () => {
    pendingWith({ ...PENDING_CHANGE, isAuthor: true });
    render(<CriteriaApproval serviceId="s1" />);
    expect(await screen.findByText('You wrote this change. Another clinical lead must approve it.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Yes, approve' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Send back' })).not.toBeInTheDocument();
  });

  it('shows the full criteria, with the owner and review line, for a first registration', async () => {
    pendingWith(PENDING_REGISTRATION);
    render(<CriteriaApproval serviceId="s1" />);
    expect(await screen.findByText('Accepts: Fall, no injury, Frailty, age 18+')).toBeInTheDocument();
    expect(screen.getByText('Does not accept: Suspected fracture')).toBeInTheDocument();
    expect(screen.getByText('Owner: Criteria owner · review by 30 Apr · version 1')).toBeInTheDocument();
  });

  it('says it cannot approve when the back end refuses the approver with 403', async () => {
    const user = userEvent.setup();
    server.use(http.post('/api/bff/criteria/:serviceId/pending/decision', () => HttpResponse.json({ code: 'forbidden' }, { status: 403 })));
    render(<CriteriaApproval serviceId="s1" />);
    await user.click(await screen.findByRole('button', { name: 'Yes, approve' }));
    expect(await screen.findByText('You cannot approve criteria for this service.')).toBeInTheDocument();
  });
});
