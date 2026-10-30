import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse, type HttpResponseResolver } from 'msw';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { resetStatusState, seenStatusActions, statusState } from '@/test/msw/handlers/registration';
import { server } from '@/test/msw/server';
import { StatusPage } from './StatusPage';
import { withApplicantHandlers } from '@/test/msw/applicant';

withApplicantHandlers();

// The applicant's status page after submitting (W27, artboards ApprovalApplicant panels 2 to 7 and
// ApprovalStates). Each state has its own words; the page shows only what the BFF passes on.

const push = vi.hoisted(() => vi.fn());
vi.mock('next/navigation', () => ({ useRouter: () => ({ push, replace: vi.fn() }) }));

const ID = 'REG-SAMPLE-1';

function state(body: Record<string, unknown>) {
  statusState.reply = { status: 200, body };
}

async function open() {
  const view = render(<StatusPage registrationId={ID} />);
  await screen.findByRole('heading', { level: 1 });
  return view;
}

beforeEach(() => {
  push.mockClear();
  resetStatusState();
});

describe('StatusPage: in review', () => {
  it('shows the tracker with Checks as the current step and its message, in the order of the screen', async () => {
    await open();
    expect(screen.getByRole('heading', { level: 1, name: 'Submitted. We are checking.' })).toBeInTheDocument();
    const tracker = screen.getByRole('list', { name: 'Registration progress' });
    const steps = within(tracker).getAllByRole('listitem');
    expect(steps).toHaveLength(5);
    expect(steps.map((item) => item.querySelector('[data-step-label]')?.textContent)).toEqual([
      'Submitted',
      'Checks',
      'Approval',
      'Test notification',
      'Live',
    ]);
    expect(within(steps[0]!).getByText('23 Oct 14:30')).toBeInTheDocument();
    expect(within(steps[1]!).getByText('In progress. The SPOA shift lead may phone your service.')).toBeInTheDocument();
    expect(steps[1]).toHaveAttribute('aria-current', 'step');
    expect(steps[0]).not.toHaveAttribute('aria-current');
    expect(screen.getByText('We will tell you by notification.')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Back to my services' })).toHaveAttribute('href', '/register/services');
  });
});

describe('StatusPage: needs changes', () => {
  it('lists the notes as a numbered list, names who sent them, and offers to fix and to phone', async () => {
    state({
      status: 'needs-changes',
      serviceName: 'UCR West',
      submittedAt: '2026-10-23T13:30:00Z',
      notes: ['The criteria owner email must be an organisation address.', 'Add the review date for the criteria.'],
      noteFrom: { role: 'SPOA shift lead', at: '2026-10-27T13:52:00Z' },
      details: { spoaPhone: '01305 123456' },
    });
    await open();
    expect(screen.getByText('Needs changes')).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 1, name: 'A few things to fix' })).toBeInTheDocument();
    const notes = screen.getByRole('list', { name: 'Notes from the shift lead' });
    expect(within(notes).getAllByRole('listitem').map((item) => item.textContent)).toEqual([
      'The criteria owner email must be an organisation address.',
      'Add the review date for the criteria.',
    ]);
    expect(screen.getByText('From SPOA shift lead, 13:52.')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Fix and resubmit' })).toHaveAttribute('href', `/register/${ID}/review`);
    expect(screen.getByRole('link', { name: '01305 123456' })).toHaveAttribute('href', 'tel:01305123456');
  });
});

describe('StatusPage: approved', () => {
  it('sends the test notification with the CSRF header and says it is sent', async () => {
    state({ status: 'approved', serviceName: 'UCR West' });
    await open();
    expect(screen.getByRole('heading', { level: 1, name: 'One last step: a test' })).toBeInTheDocument();
    expect(screen.getByText('You are not on the board until the test is answered.')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Send my test notification' }));
    expect(await screen.findByText('Test sent. Answer it on your phone.')).toBeInTheDocument();
    expect(seenStatusActions).toEqual([{ action: 'test', csrf: 'csrf-sample-token' }]);
  });
});

describe('StatusPage: live', () => {
  it('shows the first prompt time and the preview tile as Accepting, and a way to the app', async () => {
    state({ status: 'live', serviceName: 'UCR East', firstPromptAt: '2026-10-30T16:00:00Z' });
    await open();
    expect(screen.getByText('Live')).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 1, name: 'You are live' })).toBeInTheDocument();
    expect(screen.getByText('The SPOA can now see UCR East on the board. Your first prompt arrives at 16:00.')).toBeInTheDocument();
    const tile = screen.getByRole('group', { name: 'How it looks on the board' });
    expect(within(tile).getByText('UCR East')).toBeInTheDocument();
    expect(within(tile).getByText('Accepting')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Go to the app' })).toHaveAttribute('href', '/');
  });
});

describe('StatusPage: not approved', () => {
  it('shows the reason, and asking for a review posts and confirms', async () => {
    state({ status: 'not-approved', serviceName: 'UCR West', reason: 'outside the scope of the pilot' });
    await open();
    expect(screen.getByRole('heading', { level: 1, name: 'We cannot add this service yet' })).toBeInTheDocument();
    expect(screen.getByText('Reason: outside the scope of the pilot.')).toBeInTheDocument();
    expect(screen.getByText('You do not need to do anything. We will contact you if the scope changes.')).toBeInTheDocument();
    expect(screen.getByText('You can ask for a review if you think this is wrong.')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Ask for a review' }));
    expect(await screen.findByText('We have asked the shift lead to look again.')).toBeInTheDocument();
    expect(seenStatusActions).toEqual([{ action: 'review-request', csrf: 'csrf-sample-token' }]);
    expect(screen.getByRole('link', { name: 'Close' })).toHaveAttribute('href', '/register/services');
  });
});

describe('StatusPage: reverify', () => {
  it('masks the reporting phone, and "All correct" confirms the details', async () => {
    state({
      status: 'reverify',
      serviceName: 'UCR West',
      details: { spoaPhone: '01305 123456', criteriaOwner: 'Community matron', reportingPhoneEnding: '456' },
    });
    const { container } = await open();
    expect(screen.getByRole('heading', { level: 1, name: 'Are these still right?' })).toBeInTheDocument();
    expect(screen.getByText('We ask every 30 days, and whenever your reporting phone changes.')).toBeInTheDocument();
    expect(screen.getByText('07xxx xxx456')).toBeInTheDocument();
    expect(container.textContent).not.toMatch(/07\d{2}\s?\d{3}\s?\d{3}/);
    expect(screen.getByText('If the reporting phone changes, the SPOA shift lead phones your service before the new phone goes live.')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Something changed' })).toHaveAttribute('href', `/register/${ID}/review`);
    await userEvent.click(screen.getByRole('button', { name: 'All correct' }));
    expect(await screen.findByText('Your details are confirmed.')).toBeInTheDocument();
    expect(seenStatusActions).toEqual([{ action: 'confirm-details', csrf: 'csrf-sample-token' }]);
  });
});

describe('StatusPage: unknown and failing', () => {
  it('shows "We could not load your registration" for a status it does not know', async () => {
    state({ status: 'mystery', serviceName: 'UCR West' });
    render(<StatusPage registrationId={ID} />);
    expect(await screen.findByText('We could not load your registration. Try again later.')).toBeInTheDocument();
  });

  it('shows the same words when the status cannot be read', async () => {
    server.use(http.get(`/api/bff/registrations/${ID}/status`, (() => HttpResponse.json({ code: 'not-built' }, { status: 503 })) as HttpResponseResolver));
    render(<StatusPage registrationId={ID} />);
    expect(await screen.findByText('We could not load your registration. Try again later.')).toBeInTheDocument();
  });
});

describe('StatusPage: accessibility in every state', () => {
  it.each([
    ['in-review', { status: 'in-review', serviceName: 'UCR West', submittedAt: '2026-10-23T13:30:00Z' }],
    ['needs-changes', { status: 'needs-changes', serviceName: 'UCR West', notes: ['Fix it.'], noteFrom: { role: 'SPOA shift lead', at: '2026-10-27T13:52:00Z' }, details: { spoaPhone: '01305 123456' } }],
    ['approved', { status: 'approved', serviceName: 'UCR West' }],
    ['live', { status: 'live', serviceName: 'UCR East', firstPromptAt: '2026-10-30T16:00:00Z' }],
    ['not-approved', { status: 'not-approved', serviceName: 'UCR West', reason: 'outside the scope of the pilot' }],
    ['reverify', { status: 'reverify', serviceName: 'UCR West', details: { spoaPhone: '01305 123456', criteriaOwner: 'Community matron', reportingPhoneEnding: '456' } }],
  ])('has no axe violations in %s', async (_name, body) => {
    state(body);
    const { container } = await open();
    await waitFor(() => expect(container.querySelector('h1')).not.toBeNull());
    expect((await runAxe(container)).violations).toEqual([]);
  }, 30_000);
});
