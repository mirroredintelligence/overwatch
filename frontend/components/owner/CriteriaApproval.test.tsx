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
  it('shows the change as a what, was and now table, with the reason and who sent it', async () => {
    render(<CriteriaApproval serviceId="s1" />);
    expect(await screen.findByRole('heading', { level: 1, name: "What changed in UCR West's criteria" })).toBeInTheDocument();
    const diff = screen.getByRole('table', { name: 'What changed' });
    expect(diff).toHaveTextContent('Youngest age');
    expect(diff).toHaveTextContent('18');
    expect(diff).toHaveTextContent('16');
    expect(diff).toHaveTextContent('The same as the live version.');
    expect(screen.getByText('The reason given')).toBeInTheDocument();
    expect(screen.getByText('Younger patients can be seen')).toBeInTheDocument();
    expect(screen.getByText('Sent by Criteria owner')).toBeInTheDocument();
  });

  it('shows a change the table cannot split into was and now as one whole line', async () => {
    pendingWith({ ...PENDING_CHANGE, changes: ['Needs accepted changed'] });
    render(<CriteriaApproval serviceId="s1" />);
    expect(await screen.findByText('Needs accepted changed')).toBeInTheDocument();
  });

  it('puts the diff, not the approve button, in the initial focus', async () => {
    render(<CriteriaApproval serviceId="s1" />);
    const approve = await screen.findByRole('button', { name: 'Approve this change' });
    await waitFor(() => expect(screen.getByRole('region', { name: 'What changed' })).toHaveFocus());
    expect(approve).not.toHaveFocus();
  });

  it('says the two-person rule in words, and approves on "Approve this change"', async () => {
    const user = userEvent.setup();
    const { container } = render(<CriteriaApproval serviceId="s1" />);
    expect(await screen.findByText('You are the second approver.')).toBeInTheDocument();
    expect(
      screen.getByText('The person who wrote the change cannot approve it. Once you approve, the change goes live for advisors straight away. Your name and the time are logged.'),
    ).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Approve this change' }));
    expect(await screen.findByText('Approved. Advisors now see version 4.')).toBeInTheDocument();
    await waitFor(() => expect(posts()).toHaveLength(1));
    expect(posts()[0]?.body).toEqual({ decision: 'approve' });
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('asks for a note before a send back, then sends it', async () => {
    const user = userEvent.setup();
    render(<CriteriaApproval serviceId="s1" />);
    await user.click(await screen.findByRole('button', { name: 'Send it back with a note' }));
    expect(await screen.findByText('Enter a note for the criteria owner')).toBeInTheDocument();
    expect(posts()).toHaveLength(0);

    await user.type(screen.getByLabelText('Note, if sending back'), 'Keep the age at 18 until the review.');
    await user.click(screen.getByRole('button', { name: 'Send it back with a note' }));
    await waitFor(() => expect(posts()).toHaveLength(1));
    expect(posts()[0]?.body).toEqual({ decision: 'send-back', note: 'Keep the age at 18 until the review.' });
    expect(await screen.findByText('Sent back. The criteria owner sees your note.')).toBeInTheDocument();
  });

  it('hides both buttons from the author, and says another clinical lead must approve', async () => {
    pendingWith({ ...PENDING_CHANGE, isAuthor: true });
    render(<CriteriaApproval serviceId="s1" />);
    expect(await screen.findByText('You wrote this change. Another clinical lead must approve it.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Approve this change' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Send it back with a note' })).not.toBeInTheDocument();
  });

  it('opens the full criteria by default for a first registration, which has no diff, and names the version on the approve button', async () => {
    const user = userEvent.setup();
    pendingWith(PENDING_REGISTRATION);
    render(<CriteriaApproval serviceId="s1" />);
    const toggle = await screen.findByRole('button', { name: 'See the full criteria as advisors will see them' });
    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    await user.click(toggle);
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    await user.click(toggle);
    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByText('Accepts: Fall, no injury, Frailty, age 18+')).toBeInTheDocument();
    expect(screen.getByText('Does not accept: Suspected fracture')).toBeInTheDocument();
    expect(screen.getByText('Owner: Criteria owner · review by 30 Apr · version 1')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Approve version 1' })).toBeInTheDocument();
  });

  it('has no full-criteria row for a change, because the data does not carry the proposed criteria', async () => {
    render(<CriteriaApproval serviceId="s1" />);
    await screen.findByRole('heading', { level: 1, name: "What changed in UCR West's criteria" });
    expect(screen.queryByRole('button', { name: 'See the full criteria as advisors will see them' })).not.toBeInTheDocument();
  });

  it('says it cannot approve when the back end refuses the approver with 403', async () => {
    const user = userEvent.setup();
    server.use(http.post('/api/bff/criteria/:serviceId/pending/decision', () => HttpResponse.json({ code: 'forbidden' }, { status: 403 })));
    render(<CriteriaApproval serviceId="s1" />);
    await user.click(await screen.findByRole('button', { name: 'Approve this change' }));
    expect(await screen.findByText('You cannot approve criteria for this service.')).toBeInTheDocument();
  });

  it('says the decision was not recorded when the back end fails for another reason', async () => {
    const user = userEvent.setup();
    server.use(http.post('/api/bff/criteria/:serviceId/pending/decision', () => HttpResponse.json({ code: 'boom' }, { status: 500 })));
    render(<CriteriaApproval serviceId="s1" />);
    await user.click(await screen.findByRole('button', { name: 'Approve this change' }));
    expect(await screen.findByText('That decision was not recorded. Try again.')).toBeInTheDocument();
  });

  it('says the change could not be loaded when the read fails', async () => {
    pendingWith({ code: 'boom' }, 500);
    render(<CriteriaApproval serviceId="s1" />);
    expect(await screen.findByText('This change could not be loaded. Try again shortly.')).toBeInTheDocument();
  });

  it('announces the loading state in words while the change is read', async () => {
    render(<CriteriaApproval serviceId="s1" />);
    expect(screen.getByText('Loading the change.')).toBeInTheDocument();
    expect(await screen.findByRole('heading', { level: 1, name: "What changed in UCR West's criteria" })).toBeInTheDocument();
  });
});
