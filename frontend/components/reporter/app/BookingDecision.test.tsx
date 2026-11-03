import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse, delay } from 'msw';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { resetReporterRequests, seenBffRequests } from '@/test/msw/handlers/reporter';
import { server } from '@/test/msw/server';
import { BookingDecision } from './BookingDecision';

// Full-suite runs share the machine: a PIN or form test clicks many keys, so it gets more time.
vi.setConfig({ testTimeout: 20_000 });

const { push, replace } = vi.hoisted(() => ({ push: vi.fn(), replace: vi.fn() }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ push, replace }) }));

const RESPOND = '/api/bff/reporter/bookings/4821/respond';
const READ = '/api/bff/reporter/bookings/:ref';

const booking = (over: Record<string, unknown> = {}) =>
  HttpResponse.json({
    reference: '4821',
    service: 'UCR West',
    ageBand: '80+',
    need: 'Fall and frailty',
    urgency: 'Within 2 hrs',
    replyBy: '2026-10-30T14:26:00Z',
    status: 'requested',
    bookingStatus: 'requested',
    multiService: false,
    spoaPhone: '0300 000 0000',
    ...over,
  });

beforeEach(() => {
  push.mockClear();
  replace.mockClear();
  resetReporterRequests();
  server.use(http.get(READ, () => booking()));
});

async function openDecline() {
  await userEvent.click(await screen.findByRole('button', { name: 'Decline' }));
  return screen.findByRole('heading', { level: 1, name: 'Why can you not take this patient?' });
}

describe('BookingDecision (app)', () => {
  it('says what it is opening while the booking is read', async () => {
    render(<BookingDecision reference="4821" />);
    expect(screen.getByRole('status')).toHaveTextContent('Opening the booking.');
    await screen.findByRole('heading', { level: 1, name: 'UCR West' });
  });

  it('shows the reference, service, age band, need, urgency and reply-by, and no other case field', async () => {
    const { container } = render(<BookingDecision reference="4821" />);
    expect(await screen.findByRole('heading', { level: 1, name: 'UCR West' })).toBeInTheDocument();
    expect(screen.getByText('Booking request 4821')).toBeInTheDocument();
    expect(screen.getByText('Reply by 14:26')).toBeInTheDocument();
    const facts = screen.getByText('Age band').closest('dl') as HTMLElement;
    expect(within(facts).getByText('80+')).toBeInTheDocument();
    expect(within(facts).getByText('Fall and frailty')).toBeInTheDocument();
    expect(within(facts).getByText('Within 2 hrs')).toBeInTheDocument();
    expect(screen.getByText('Opening this page booked nothing. It is booked when you press Confirm.')).toBeInTheDocument();
    // The note says no patient name is shown; nothing of the case itself is.
    expect(screen.getByText('Referral details follow in the referral system. No patient name is shown here.')).toBeInTheDocument();
    expect(container.textContent).not.toMatch(/nhs|postcode/i);
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('confirms with an Idempotency-Key and shows Booked', async () => {
    render(<BookingDecision reference="4821" />);
    await userEvent.click(await screen.findByRole('button', { name: 'Confirm booking' }));
    expect(await screen.findByRole('heading', { level: 1, name: 'Booked' })).toBeInTheDocument();
    expect(screen.getByText('Reference 4821, UCR West. Confirmed 14:19. The advisor has been told.')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: '0300 000 0000' })).toHaveAttribute('href', 'tel:03000000000');
    expect(screen.queryByRole('link', { name: 'Tell us something changed' })).toBeNull();
    const sent = seenBffRequests.find((r) => r.path === RESPOND);
    expect(sent?.body).toEqual({ decision: 'confirm' });
    expect(sent?.idempotencyKey).toMatch(/.{8,}/);
  });

  it('opens the decline reasons, posts nothing until Decline booking, and sends the chosen reason', async () => {
    render(<BookingDecision reference="4821" />);
    expect(await openDecline()).toHaveFocus();
    expect(seenBffRequests.find((r) => r.path === RESPOND)).toBeUndefined();
    await userEvent.click(screen.getByRole('radio', { name: 'Outside our criteria' }));
    expect(screen.getByRole('radio', { name: 'Outside our criteria' })).toHaveAttribute('aria-checked', 'true');
    await userEvent.click(screen.getByRole('button', { name: 'Decline booking' }));
    expect(await screen.findByRole('heading', { level: 1, name: 'Declined' })).toBeInTheDocument();
    expect(screen.getByText('Reference 4821 declined. The advisor has been told.')).toBeInTheDocument();
    expect(seenBffRequests.find((r) => r.path === RESPOND)?.body).toEqual({ decision: 'decline', reason: 'outside-criteria' });
  });

  it('declines with no reason field when none is chosen, and can go back to the request first', async () => {
    render(<BookingDecision reference="4821" />);
    await openDecline();
    await userEvent.click(screen.getByRole('button', { name: 'Back to the request' }));
    expect(await screen.findByRole('button', { name: 'Confirm booking' })).toBeInTheDocument();
    await openDecline();
    await userEvent.click(screen.getByRole('button', { name: 'Decline booking' }));
    await screen.findByRole('heading', { level: 1, name: 'Declined' });
    expect(seenBffRequests.find((r) => r.path === RESPOND)?.body).toEqual({ decision: 'decline' });
  });

  it('keeps the data-el ids of the buttons and the reasons group', async () => {
    render(<BookingDecision reference="4821" />);
    expect(await screen.findByRole('button', { name: 'Confirm booking' })).toHaveAttribute('data-el', 'REP-BOOK-CONFIRM-BTN');
    expect(screen.getByRole('button', { name: 'Decline' })).toHaveAttribute('data-el', 'REP-BOOK-DECLINE-BTN');
    await openDecline();
    expect(screen.getByRole('radiogroup')).toHaveAttribute('data-el', 'REP-BOOK-REASONS');
  });

  it('disables the buttons while the decision is sent, so a second press sends nothing', async () => {
    server.use(
      http.post(RESPOND, async ({ request }) => {
        // The override replaces the default handler, so it records the send itself.
        seenBffRequests.push({ path: RESPOND, method: 'POST', body: await request.json() });
        await delay(150);
        return HttpResponse.json({ status: 'confirmed', confirmedAt: '2026-10-30T14:19:00Z' });
      }),
    );
    render(<BookingDecision reference="4821" />);
    const confirm = await screen.findByRole('button', { name: 'Confirm booking' });
    await userEvent.click(confirm);
    expect(confirm).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Decline' })).toBeDisabled();
    await userEvent.click(confirm);
    await waitFor(() => expect(screen.getByRole('heading', { level: 1, name: 'Booked' })).toBeInTheDocument());
    expect(seenBffRequests.filter((r) => r.path === RESPOND)).toHaveLength(1);
  });

  it('disables Decline booking and Back while the decline is sent', async () => {
    server.use(
      http.post(RESPOND, async ({ request }) => {
        seenBffRequests.push({ path: RESPOND, method: 'POST', body: await request.json() });
        await delay(150);
        return HttpResponse.json({ status: 'declined' });
      }),
    );
    render(<BookingDecision reference="4821" />);
    await openDecline();
    const send = screen.getByRole('button', { name: 'Decline booking' });
    await userEvent.click(send);
    expect(send).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Back to the request' })).toBeDisabled();
    await userEvent.click(send);
    await screen.findByRole('heading', { level: 1, name: 'Declined' });
    expect(seenBffRequests.filter((r) => r.path === RESPOND)).toHaveLength(1);
  });

  it('keeps the request and says what happened when the answer could not be sent, so it can be tried again', async () => {
    server.use(http.post(RESPOND, () => HttpResponse.json({ code: 'oops' }, { status: 500 })));
    render(<BookingDecision reference="4821" />);
    await userEvent.click(await screen.findByRole('button', { name: 'Confirm booking' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('We could not send that. Try again.');
    expect(screen.getByRole('button', { name: 'Confirm booking' })).toBeEnabled();
    expect(screen.queryByRole('heading', { name: 'Booked' })).toBeNull();
  });

  it('says the request expired, with no buttons', async () => {
    server.use(http.get(READ, () => booking({ status: 'expired', bookingStatus: 'expired', multiService: true, service: 'UCR East' })));
    const { container } = render(<BookingDecision reference="4821" />);
    expect(await screen.findByRole('heading', { level: 1, name: 'This request has expired' })).toBeInTheDocument();
    expect(screen.getByText('This request expired at 14:26. The coordination team will phone you if they still need you.')).toBeInTheDocument();
    expect(screen.queryByRole('button')).toBeNull();
    expect(container.querySelector('[data-tone="closed"]')).not.toBeNull();
  });

  it('names the service on the confirm button when the phone holds several services', async () => {
    server.use(http.get(READ, () => booking({ service: 'UCR East', multiService: true })));
    render(<BookingDecision reference="4821" />);
    expect(await screen.findByRole('button', { name: 'Confirm booking for UCR East' })).toBeInTheDocument();
    expect(screen.getByText('UCR East only')).toBeInTheDocument();
  });

  it('shows the coordination number only when the tenant has one, and says to phone the team without a number otherwise', async () => {
    server.use(
      http.get(READ, () => booking({ ageBand: null, urgency: null, status: 'confirmed', bookingStatus: 'confirmed', spoaPhone: null, confirmedAt: '2026-10-30T14:19:00Z' })),
    );
    render(<BookingDecision reference="4821" />);
    expect(await screen.findByRole('heading', { level: 1, name: 'Booked' })).toBeInTheDocument();
    expect(screen.getByText('Reference 4821, UCR West. Confirmed 14:19. The advisor has been told.')).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 2, name: 'Something changed?' })).toBeInTheDocument();
    expect(screen.getByText('Phone the coordination team.')).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /\d/ })).toBeNull();
  });

  it('leaves out an age band and an urgency the back end did not give', async () => {
    server.use(http.get(READ, () => booking({ ageBand: null, urgency: null, spoaPhone: null })));
    render(<BookingDecision reference="4821" />);
    expect(await screen.findByText('Fall and frailty')).toBeInTheDocument();
    expect(screen.queryByText('Age band')).toBeNull();
    expect(screen.queryByText('Wanted')).toBeNull();
  });

  it('shows what the back end holds when the booking was answered meanwhile (409), and does not call it done by us', async () => {
    let reads = 0;
    server.use(
      http.get(READ, () => {
        reads += 1;
        return booking({ urgency: null, status: reads === 1 ? 'requested' : 'declined', bookingStatus: reads === 1 ? 'requested' : 'declined', spoaPhone: null });
      }),
      http.post(RESPOND, () => HttpResponse.json({ code: 'conflict' }, { status: 409 })),
    );
    render(<BookingDecision reference="4821" />);
    await userEvent.click(await screen.findByRole('button', { name: 'Confirm booking' }));
    expect(await screen.findByRole('heading', { level: 1, name: 'Declined' })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Booked' })).toBeNull();
  });

  it('says it could not load the booking, in plain words', async () => {
    server.use(http.get(READ, () => HttpResponse.json({ code: 'not-found' }, { status: 404 })));
    render(<BookingDecision reference="4821" />);
    expect(await screen.findByRole('alert')).toHaveTextContent('We could not load this booking. Try again shortly.');
  });

  it('goes to the PIN when the session has ended, from the read or from the answer', async () => {
    server.use(http.get(READ, () => HttpResponse.json({ code: 'session-ended' }, { status: 401 })));
    render(<BookingDecision reference="4821" />);
    await waitFor(() => expect(replace).toHaveBeenCalledWith('/app/pin'));
  });

  it('goes to the PIN when the answer says the session has ended', async () => {
    server.use(http.post(RESPOND, () => HttpResponse.json({ code: 'session-ended' }, { status: 401 })));
    render(<BookingDecision reference="4821" />);
    await userEvent.click(await screen.findByRole('button', { name: 'Confirm booking' }));
    await waitFor(() => expect(replace).toHaveBeenCalledWith('/app/pin'));
  });
});
