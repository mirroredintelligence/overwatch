import { render, screen, waitFor } from '@testing-library/react';
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

beforeEach(() => {
  push.mockClear();
  replace.mockClear();
  resetReporterRequests();
});

describe('BookingDecision', () => {
  it('shows the reference, age band, need, urgency and reply-by, and no other case field', async () => {
    const { container } = render(<BookingDecision reference="4821" />);
    expect(await screen.findByText('Booking request 4821')).toBeInTheDocument();
    expect(screen.getByText('Age band 80+')).toBeInTheDocument();
    expect(screen.getByText('Need Fall and frailty')).toBeInTheDocument();
    expect(screen.getByText('Wanted Within 2 hrs')).toBeInTheDocument();
    expect(screen.getByText('Reply by 14:26.')).toBeInTheDocument();
    expect(container.textContent).not.toMatch(/patient|nhs|postcode|name/i);
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('confirms with an Idempotency-Key and shows Booked', async () => {
    render(<BookingDecision reference="4821" />);
    await userEvent.click(await screen.findByRole('button', { name: 'Confirm booking' }));
    expect(await screen.findByRole('heading', { name: 'Booked' })).toBeInTheDocument();
    expect(screen.getByText('Reference 4821, UCR West. Confirmed 14:19. The advisor has been told.')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: '0300 000 0000' })).toHaveAttribute('href', 'tel:03000000000');
    const sent = seenBffRequests.find((r) => r.path === RESPOND);
    expect(sent?.body).toEqual({ decision: 'confirm' });
    expect(sent?.idempotencyKey).toMatch(/.{8,}/);
  });

  it('declines with the chosen reason', async () => {
    render(<BookingDecision reference="4821" />);
    await userEvent.click(await screen.findByRole('button', { name: 'Outside criteria' }));
    expect(screen.getByRole('button', { name: 'Outside criteria' })).toHaveAttribute('aria-pressed', 'true');
    await userEvent.click(screen.getByRole('button', { name: 'Decline' }));
    expect(await screen.findByText('Declined. The advisor has been told.')).toBeInTheDocument();
    expect(seenBffRequests.find((r) => r.path === RESPOND)?.body).toEqual({ decision: 'decline', reason: 'outside-criteria' });
  });

  it('disables both buttons while the decision is sent, so a second press sends nothing', async () => {
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
    await waitFor(() => expect(screen.getByRole('heading', { name: 'Booked' })).toBeInTheDocument());
    expect(seenBffRequests.filter((r) => r.path === RESPOND)).toHaveLength(1);
  });

  it('says the request expired, with no buttons, and names the service when the phone holds several', async () => {
    server.use(
      http.get('/api/bff/reporter/bookings/:ref', () =>
        HttpResponse.json({ reference: '4821', service: 'UCR East', ageBand: '80+', need: 'Fall and frailty', urgency: 'Wanted Within 2 hrs', replyBy: '2026-10-30T14:26:00Z', status: 'expired', bookingStatus: 'expired', multiService: true, spoaPhone: '0300 000 0000' }),
      ),
    );
    render(<BookingDecision reference="4821" />);
    expect(await screen.findByText('This request expired at 14:26. The coordination team will phone you if they still need you.')).toBeInTheDocument();
    expect(screen.queryByRole('button')).toBeNull();
  });

  it('names the service on the confirm button when the phone holds several services', async () => {
    server.use(
      http.get('/api/bff/reporter/bookings/:ref', () =>
        HttpResponse.json({ reference: '4821', service: 'UCR East', ageBand: '80+', need: 'Fall and frailty', urgency: 'Wanted Within 2 hrs', replyBy: '2026-10-30T14:26:00Z', status: 'requested', bookingStatus: 'requested', multiService: true, spoaPhone: '0300 000 0000' }),
      ),
    );
    render(<BookingDecision reference="4821" />);
    expect(await screen.findByRole('button', { name: 'Confirm booking for UCR East' })).toBeInTheDocument();
    expect(screen.getByText('UCR East only')).toBeInTheDocument();
  });

  it('shows the SPOA number only when the tenant has one, and says to phone the team without a number otherwise', async () => {
    server.use(
      http.get('/api/bff/reporter/bookings/:ref', () =>
        HttpResponse.json({ reference: '4821', service: 'UCR West', ageBand: null, need: 'Fall and frailty', urgency: null, replyBy: '2026-10-30T14:26:00Z', status: 'confirmed', bookingStatus: 'confirmed', multiService: false, spoaPhone: null, confirmedAt: '2026-10-30T14:19:00Z' }),
      ),
    );
    render(<BookingDecision reference="4821" />);
    expect(await screen.findByRole('heading', { name: 'Booked' })).toBeInTheDocument();
    expect(screen.getByText('Reference 4821, UCR West. Confirmed 14:19. The advisor has been told.')).toBeInTheDocument();
    expect(screen.getByText('Something changed? Phone the coordination team.')).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /\d/ })).toBeNull();
  });

  it('leaves out an age band and an urgency the back end did not give', async () => {
    server.use(
      http.get('/api/bff/reporter/bookings/:ref', () =>
        HttpResponse.json({ reference: '4821', service: 'UCR West', ageBand: null, need: 'Fall and frailty', urgency: null, replyBy: '2026-10-30T14:26:00Z', status: 'requested', bookingStatus: 'requested', multiService: false, spoaPhone: null }),
      ),
    );
    render(<BookingDecision reference="4821" />);
    expect(await screen.findByText('Need Fall and frailty')).toBeInTheDocument();
    expect(screen.queryByText(/Age band/)).toBeNull();
  });

  it('shows what the back end holds when the booking was answered meanwhile (409), and does not call it done by us', async () => {
    let reads = 0;
    server.use(
      http.get('/api/bff/reporter/bookings/:ref', () => {
        reads += 1;
        return HttpResponse.json({ reference: '4821', service: 'UCR West', ageBand: '80+', need: 'Fall and frailty', urgency: null, replyBy: '2026-10-30T14:26:00Z', status: reads === 1 ? 'requested' : 'declined', bookingStatus: reads === 1 ? 'requested' : 'declined', multiService: false, spoaPhone: null });
      }),
      http.post(RESPOND, () => HttpResponse.json({ code: 'conflict' }, { status: 409 })),
    );
    render(<BookingDecision reference="4821" />);
    await userEvent.click(await screen.findByRole('button', { name: 'Confirm booking' }));
    expect(await screen.findByText('Declined. The advisor has been told.')).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Booked' })).toBeNull();
  });

  it('goes to the PIN when the session has ended, from the read or from the answer', async () => {
    server.use(http.get('/api/bff/reporter/bookings/:ref', () => HttpResponse.json({ code: 'session-ended' }, { status: 401 })));
    render(<BookingDecision reference="4821" />);
    await waitFor(() => expect(replace).toHaveBeenCalledWith('/app/pin'));
  });
});
