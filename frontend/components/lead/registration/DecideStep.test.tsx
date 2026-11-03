import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { DECISION_OPEN } from '@/test/fixtures/registration';
import { resetRegistrationRequests, seenRegistrationRequests } from '@/test/msw/handlers/registrations';
import { server } from '@/test/msw/server';
import { DecideStep } from './DecideStep';

const DECISION = '/api/bff/registrations/r1/decision';
beforeEach(() => resetRegistrationRequests());
const posts = () => seenRegistrationRequests.filter((r) => r.method === 'POST' && r.path === DECISION);

function decisionWith(missing: string[]) {
  server.use(
    http.get('/api/bff/registrations/:id/decision', () =>
      HttpResponse.json({ ...DECISION_OPEN, missing }, { headers: { 'Cache-Control': 'no-store' } }),
    ),
  );
}

const SECOND_APPROVAL = 'Criteria second approval (waiting for the clinical lead)';

// The user-event tests here run slowly when the whole suite shares the machine; the budget is per file.
vi.setConfig({ testTimeout: 15_000 });

describe('DecideStep', () => {
  it('keeps Approve a real disabled button and sends nothing while a check is missing, and names the missing check', async () => {
    decisionWith(['Call-back done']);
    const user = userEvent.setup();
    const { container } = render(<DecideStep id="r1" />);
    const approve = await screen.findByRole('button', { name: 'Approve (not yet available)' });
    expect(approve).toBeDisabled();
    expect(screen.getByRole('status')).toHaveTextContent('Call-back done');

    await user.click(approve);
    expect(posts()).toHaveLength(0);
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('says in the Approve button what it waits for, taken from the back-end list', async () => {
    decisionWith([SECOND_APPROVAL]);
    render(<DecideStep id="r1" />);
    const approve = await screen.findByRole('button', { name: 'Approve (waiting for the clinical lead)' });
    expect(approve).toBeDisabled();
  });

  it('shows the heading, the step number and each check with a word, not a colour alone', async () => {
    decisionWith(['Call-back done', SECOND_APPROVAL]);
    render(<DecideStep id="r1" />);
    expect(await screen.findByRole('heading', { level: 1, name: 'Decide' })).toBeInTheDocument();
    expect(screen.getByText('Check 4 of 4')).toBeInTheDocument();
    const list = screen.getByRole('list', { name: 'Before you can approve' });
    const rows = within(list).getAllByRole('listitem');
    expect(rows).toHaveLength(4);
    expect(rows[0]).toHaveTextContent('Automatic checks passed or explained');
    expect(rows[0]).toHaveTextContent('Done');
    expect(rows[1]).toHaveTextContent('Call-back done');
    expect(rows[1]).toHaveTextContent('Missing');
    expect(rows[3]).toHaveTextContent('Missing');
  });

  it('lists a missing item the page does not know by name, so the back-end list is shown whole', async () => {
    decisionWith(['Evidence of registration']);
    render(<DecideStep id="r1" />);
    const list = await screen.findByRole('list', { name: 'Before you can approve' });
    expect(within(list).getByText('Evidence of registration')).toBeInTheDocument();
    expect(within(list).getAllByRole('listitem')).toHaveLength(5);
  });

  it('enables Approve once nothing is missing, and approves on that press', async () => {
    decisionWith([]);
    const user = userEvent.setup();
    render(<DecideStep id="r1" />);
    const approve = await screen.findByRole('button', { name: 'Approve' });
    expect(approve).toBeEnabled();
    await user.click(approve);
    await waitFor(() => expect(posts()).toHaveLength(1));
    expect(posts()[0]?.body).toEqual({ action: 'approve' });
    expect(await screen.findByText('Approved.')).toBeInTheDocument();
  });

  it('asks for a note before a send back, then sends it and says so', async () => {
    decisionWith([]);
    const user = userEvent.setup();
    render(<DecideStep id="r1" />);
    await user.click(await screen.findByRole('button', { name: 'Send back with a note' }));
    expect(await screen.findByText('Enter a note for the applicant')).toBeInTheDocument();
    expect(posts()).toHaveLength(0);

    await user.type(screen.getByLabelText('Note to the applicant'), 'Please add an organisation address.');
    await user.click(screen.getByRole('button', { name: 'Send back with a note' }));
    expect(await screen.findByText('Sent back. The applicant sees your note.')).toBeInTheDocument();
    expect(posts()[0]?.body).toEqual({ action: 'send-back', note: 'Please add an organisation address.' });
  });

  it('sends a not-approved decision with its note', async () => {
    decisionWith([SECOND_APPROVAL]);
    const user = userEvent.setup();
    render(<DecideStep id="r1" />);
    await user.type(await screen.findByLabelText('Note to the applicant'), 'Outside the pilot.');
    await user.click(screen.getByRole('button', { name: 'Not approved: out of scope' }));
    expect(await screen.findByText('Not approved. The applicant sees your note.')).toBeInTheDocument();
    expect(posts()[0]?.body).toEqual({ action: 'not-approve', note: 'Outside the pilot.' });
  });

  it('says what is loading while the decision loads, in the shared shimmer', () => {
    render(<DecideStep id="r1" />);
    expect(screen.getByRole('status')).toHaveTextContent('Loading the decision.');
  });

  it('says nothing was recorded when the decision cannot be loaded', async () => {
    server.use(http.get('/api/bff/registrations/:id/decision', () => HttpResponse.json({}, { status: 500 })));
    render(<DecideStep id="r1" />);
    expect(await screen.findByText('The decision could not be loaded. Try again shortly.')).toBeInTheDocument();
  });
});
