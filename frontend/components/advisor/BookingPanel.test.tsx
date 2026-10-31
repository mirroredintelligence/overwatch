import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { http, HttpResponse } from 'msw';
import { server } from '@/test/msw/server';
import { FakeStream } from '@/test/fakeStream';
import { runAxe } from '@/test/a11y';
import { byEl } from '@/test/el';
import { BOOKING_ID, CASE_REF, SERVICE_ID, SERVICE_PHONE, SERVICE_WITH_OPEN_REQUEST, STATE_CONFIRMED, STATE_NOT_REACHED, STATE_REQUESTED, STATE_WITHDRAWN, STATE_WITHDRAWN_ACKNOWLEDGED } from '@/test/fixtures/bookings';
import { bookingStore, caseBookings, resetBookingRequests, seenAcknowledgements, seenBookingCancels, seenBookingCaseReads, seenBookingPosts, seenBookingReads } from '@/test/msw/handlers/bookings';
import { BookingPanel } from './BookingPanel';

// The "Request booking" control and the booking card it opens (W20). The live stream and the
// clock are the test's: a FakeStream stands for /api/bff/events, and the card's timers are fake.

const CSRF = 'csrf-value-for-the-panel';

function setCsrfCookie() {
  document.cookie = `diucs_csrf=${CSRF}; path=/`;
}

let stream: FakeStream;

const onSeeOptions = vi.fn();

function renderPanel(serviceId = SERVICE_ID) {
  return render(
    <BookingPanel
      caseRef={CASE_REF}
      serviceId={serviceId}
      serviceName="UCR West"
      servicePhone={SERVICE_PHONE}
      onSeeOptions={onSeeOptions}
      now={() => Date.parse('2026-10-30T14:16:30Z')}
      openStream={() => {
        stream = new FakeStream();
        return stream;
      }}
    />,
  );
}

/** Requests a booking, then makes the back end hold `next` and tells the card so with an event. */
async function requestThenMove(next: Record<string, unknown>) {
  renderPanel();
  await userEvent.click(screen.getByRole('button', { name: 'Request booking' }));
  await screen.findByText('Requested');
  bookingStore.current = next as typeof bookingStore.current;
  stream.emit('booking.updated', JSON.stringify({ serviceId: SERVICE_ID, kind: 'booking', changedAt: '2026-10-30T14:41:00Z' }));
}

beforeEach(() => {
  resetBookingRequests();
  setCsrfCookie();
  vi.useRealTimers();
  onSeeOptions.mockClear();
});

describe('BookingPanel: Request booking', () => {
  it('posts once with the CSRF header and an Idempotency-Key, then shows the requested text with 14:21 and 14:26', async () => {
    const { container } = renderPanel();
    await userEvent.click(screen.getByRole('button', { name: 'Request booking' }));
    expect(await screen.findByText('Text delivered 14:16. Waiting for CONFIRMED. Phone prompt at 14:21. Request expires 14:26.')).toBeInTheDocument();
    expect(seenBookingPosts).toHaveLength(1);
    expect(seenBookingPosts[0]?.body).toEqual({ caseRef: CASE_REF, serviceId: SERVICE_ID });
    expect(seenBookingPosts[0]?.csrf).toBe(CSRF);
    expect(seenBookingPosts[0]?.idempotencyKey).toMatch(/^[0-9a-f-]{36}$/);
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('posts once when the button is pressed twice quickly', async () => {
    renderPanel();
    const button = screen.getByRole('button', { name: 'Request booking' });
    await userEvent.dblClick(button);
    await screen.findByText('Requested');
    expect(seenBookingPosts).toHaveLength(1);
  });

  it('says the service already has a request waiting when the back end answers 409', async () => {
    renderPanel(SERVICE_WITH_OPEN_REQUEST);
    await userEvent.click(screen.getByRole('button', { name: 'Request booking' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('UCR West already has a request waiting. Phone them instead.');
    expect(screen.queryByText('Requested')).toBeNull();
  });
});

describe('BookingPanel: live updates', () => {
  it('refetches when a booking.updated event names this service, and shows Booked', async () => {
    renderPanel();
    await userEvent.click(screen.getByRole('button', { name: 'Request booking' }));
    await screen.findByText('Requested');
    bookingStore.current = STATE_CONFIRMED;
    stream.emit('booking.updated', JSON.stringify({ serviceId: SERVICE_ID, kind: 'booking', changedAt: '2026-10-30T14:19:00Z' }));
    expect(await screen.findByText('Booked')).toBeInTheDocument();
    expect(screen.getByText('Confirmed 14:19')).toBeInTheDocument();
    expect(seenBookingReads).toEqual([BOOKING_ID]);
  });

  it('refetches on a board event that names this service: the back end sends `board`, not `booking.updated` (routes_events.py)', async () => {
    renderPanel();
    await userEvent.click(screen.getByRole('button', { name: 'Request booking' }));
    await screen.findByText('Requested');
    bookingStore.current = STATE_CONFIRMED;
    stream.emit('board', JSON.stringify({ serviceId: SERVICE_ID, kind: 'capacity', changedAt: '2026-10-30T14:19:00Z' }));

    expect(await screen.findByText('Booked')).toBeInTheDocument();
    expect(seenBookingReads).toEqual([BOOKING_ID]);
  });

  it('ignores a board event for another service', async () => {
    renderPanel();
    await userEvent.click(screen.getByRole('button', { name: 'Request booking' }));
    await screen.findByText('Requested');
    stream.emit('board', JSON.stringify({ serviceId: 'ucr-other', kind: 'capacity', changedAt: '2026-10-30T14:19:00Z' }));
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(seenBookingReads).toHaveLength(0);
  });

  it('ignores a booking.updated event for another service', async () => {
    renderPanel();
    await userEvent.click(screen.getByRole('button', { name: 'Request booking' }));
    await screen.findByText('Requested');
    stream.emit('booking.updated', JSON.stringify({ serviceId: 'ucr-other', kind: 'booking', changedAt: '2026-10-30T14:19:00Z' }));
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(seenBookingReads).toHaveLength(0);
    expect(screen.getByText('Requested')).toBeInTheDocument();
  });

  it('closes the stream when it unmounts', async () => {
    const { unmount } = renderPanel();
    await userEvent.click(screen.getByRole('button', { name: 'Request booking' }));
    await screen.findByText('Requested');
    unmount();
    expect(stream.closed).toBe(true);
  });
});

describe('BookingPanel: cancelling (W21)', () => {
  it('cancels a confirmed booking with the reason chosen, posts once with CSRF, and shows Cancelled', async () => {
    renderPanel();
    await userEvent.click(screen.getByRole('button', { name: 'Request booking' }));
    await screen.findByText('Requested');
    bookingStore.current = STATE_CONFIRMED;
    stream.emit('booking.updated', JSON.stringify({ serviceId: SERVICE_ID, kind: 'booking', changedAt: '2026-10-30T14:19:00Z' }));
    await screen.findByText('Booked');
    await userEvent.click(screen.getByRole('button', { name: 'Cancel booking' }));
    const confirm = screen.getByRole('button', { name: 'Cancel booking', hidden: false });
    expect(confirm).toBeDisabled();
    await userEvent.click(screen.getByRole('button', { name: 'No longer needed' }));
    await userEvent.click(confirm);
    expect(await screen.findByText('Cancelled')).toBeInTheDocument();
    expect(seenBookingCancels).toEqual([
      { id: BOOKING_ID, body: { reason: 'no-longer-needed' }, csrf: CSRF, idempotencyKey: expect.stringMatching(/^[0-9a-f-]{36}$/) },
    ]);
    await userEvent.click(screen.getByRole('button', { name: 'Choose another option' }));
    expect(onSeeOptions).toHaveBeenCalledTimes(1);
  });

  it('asks about the request on a request not yet answered, and Keep request posts nothing', async () => {
    renderPanel();
    await userEvent.click(screen.getByRole('button', { name: 'Request booking' }));
    await screen.findByText('Requested');
    await userEvent.click(screen.getByRole('button', { name: 'Cancel request' }));
    expect(screen.getByText('Cancel the request to UCR West?')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Keep request' }));
    expect(seenBookingCancels).toHaveLength(0);
    expect(screen.getByText('Requested')).toBeInTheDocument();
  });

  it('shows the state-changed message when the booking moved on before the cancel', async () => {
    renderPanel();
    await userEvent.click(screen.getByRole('button', { name: 'Request booking' }));
    await screen.findByText('Requested');
    bookingStore.refuseCancel = true;
    await userEvent.click(screen.getByRole('button', { name: 'Cancel request' }));
    await userEvent.click(screen.getByRole('button', { name: 'Caller declined' }));
    await userEvent.click(screen.getByRole('button', { name: 'Cancel request' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('This booking changed before you cancelled. Check its status.');
  });
});

describe('BookingPanel: withdrawal and not-reached alerts (W21, DEC-854)', () => {
  it('opens the withdrawal alert on booking.updated on the shared dialog, and says why', async () => {
    await requestThenMove(STATE_WITHDRAWN);
    const alert = await screen.findByRole('alertdialog', { name: 'UCR West withdrew' });
    expect(screen.getByText('Reason: staffing. Withdrawn 14:41.')).toBeInTheDocument();
    expect(document.activeElement).toBe(alert);
  });

  it('acknowledges through the BFF, once, from "I have phoned the caller", and the alert closes', async () => {
    await requestThenMove(STATE_WITHDRAWN);
    await userEvent.click(await screen.findByRole('button', { name: 'I have phoned the caller' }));

    await vi.waitFor(() => expect(screen.queryByRole('alertdialog')).toBeNull());
    expect(seenAcknowledgements).toEqual([{ id: BOOKING_ID, csrf: CSRF, idempotencyKey: expect.stringMatching(/^[0-9a-f-]{36}$/) }]);
    expect(document.querySelector('[data-el="ADV-WITHDRAWN-NOTICE"]')).toBeNull();
  });

  it('acknowledges from "The caller is already being helped" too', async () => {
    await requestThenMove(STATE_WITHDRAWN);
    await userEvent.click(await screen.findByRole('button', { name: 'The caller is already being helped' }));

    await vi.waitFor(() => expect(seenAcknowledgements).toHaveLength(1));
  });

  it('does not acknowledge on "See options again": the alert gives way to a standing notice and the escalation keeps running (the old first-action rule fails here)', async () => {
    await requestThenMove(STATE_WITHDRAWN);
    await userEvent.click(await screen.findByRole('button', { name: 'See options again' }));

    expect(onSeeOptions).toHaveBeenCalledTimes(1);
    expect(seenAcknowledgements).toEqual([]);
    expect(screen.queryByRole('alertdialog')).toBeNull();
    const notice = await vi.waitFor(() => byEl('ADV-WITHDRAWN-NOTICE'));
    expect(notice).toHaveTextContent('UCR West withdrew. This is not answered yet: phone the caller, then answer the alert.');
  });

  it('does not acknowledge on "Ask a clinical advisor", and the notice stays', async () => {
    const onAskClinical = vi.fn();
    render(
      <BookingPanel
        caseRef={CASE_REF}
        serviceId={SERVICE_ID}
        serviceName="UCR West"
        servicePhone={SERVICE_PHONE}
        onAskClinical={onAskClinical}
        openStream={() => {
          stream = new FakeStream();
          return stream;
        }}
      />,
    );
    await userEvent.click(screen.getByRole('button', { name: 'Request booking' }));
    await screen.findByText('Requested');
    bookingStore.current = STATE_WITHDRAWN as typeof bookingStore.current;
    stream.emit('booking.updated', JSON.stringify({ serviceId: SERVICE_ID, kind: 'booking', changedAt: '2026-10-30T14:41:00Z' }));
    await userEvent.click(await screen.findByRole('button', { name: 'Ask a clinical advisor' }));

    expect(onAskClinical).toHaveBeenCalledTimes(1);
    expect(seenAcknowledgements).toEqual([]);
    await vi.waitFor(() => expect(byEl('ADV-WITHDRAWN-NOTICE')).toBeInTheDocument());
  });

  it('does not acknowledge on Escape, and the notice reopens the alert so it can be answered', async () => {
    await requestThenMove(STATE_WITHDRAWN);
    await screen.findByRole('alertdialog');
    await userEvent.keyboard('{Escape}');

    expect(seenAcknowledgements).toEqual([]);
    await userEvent.click(await screen.findByRole('button', { name: 'Open the alert' }));
    await userEvent.click(await screen.findByRole('button', { name: 'I have phoned the caller' }));

    await vi.waitFor(() => expect(seenAcknowledgements).toHaveLength(1));
    await vi.waitFor(() => expect(document.querySelector('[data-el="ADV-WITHDRAWN-NOTICE"]')).toBeNull());
  });

  it('keeps the alert open and says so when the acknowledgement fails, so the escalation is never believed stopped', async () => {
    server.use(http.post('/api/bff/bookings/:id/acknowledge', () => HttpResponse.json({ code: 'exception' }, { status: 502 })));
    await requestThenMove(STATE_WITHDRAWN);
    await userEvent.click(await screen.findByRole('button', { name: 'I have phoned the caller' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('The answer could not be sent. The shift lead will still be told. Try again.');
    expect(screen.getByRole('alertdialog')).toBeInTheDocument();
  });

  it('shows the not-reached alert for a not-reached booking, answered the same way', async () => {
    await requestThenMove(STATE_NOT_REACHED);
    expect(await screen.findByRole('alertdialog', { name: 'UCR West could not reach the patient' })).toBeInTheDocument();
    expect(screen.getByText('Reason: No answer at the door. Reported 14:41.')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'I have phoned the caller' }));
    await vi.waitFor(() => expect(seenAcknowledgements).toHaveLength(1));
  });

  it('ignores the withdrawal alert when the booking is still only requested', async () => {
    renderPanel();
    await userEvent.click(screen.getByRole('button', { name: 'Request booking' }));
    await screen.findByText('Requested');
    expect(screen.queryByRole('alertdialog')).toBeNull();
    expect(STATE_REQUESTED.status).toBe('requested');
  });

  it('has no axe violations with the alert open or with the standing notice', async () => {
    await requestThenMove(STATE_WITHDRAWN);
    await screen.findByRole('alertdialog');
    expect(await runAxe(document.body)).toHaveNoViolations();
    await userEvent.click(screen.getByRole('button', { name: 'See options again' }));
    await vi.waitFor(() => byEl('ADV-WITHDRAWN-NOTICE'));
    expect(await runAxe(document.body)).toHaveNoViolations();
  });
});


describe('BookingPanel: the card comes back after a reload (WB4)', () => {
  it('reads the bookings of the case once, and shows the card for the service that has one', async () => {
    caseBookings.current = [STATE_CONFIRMED];
    renderPanel();
    expect(await screen.findByText('Booked')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Request booking' })).toBeNull();
    expect(seenBookingCaseReads).toEqual([CASE_REF]);
  });

  it('offers Request booking when the case has no booking for this service', async () => {
    caseBookings.current = [{ ...STATE_CONFIRMED, serviceId: 'another-service' }];
    renderPanel();
    expect(await screen.findByRole('button', { name: 'Request booking' })).toBeInTheDocument();
    expect(screen.queryByText('Booked')).toBeNull();
  });

  it('shows the latest booking of the service when it has had more than one', async () => {
    caseBookings.current = [
      { ...STATE_REQUESTED, id: 'bk-old', status: 'declined', declinedAt: '2026-10-30T13:19:00Z', requestedAt: '2026-10-30T13:16:00Z' },
      { ...STATE_REQUESTED, id: 'bk-new' },
    ];
    renderPanel();
    expect(await screen.findByText('Requested')).toBeInTheDocument();
    expect(screen.queryByText('Declined')).toBeNull();
  });

  it('does not open a withdrawal alert that was answered before the reload', async () => {
    caseBookings.current = [STATE_WITHDRAWN_ACKNOWLEDGED];
    renderPanel();
    expect(await screen.findByText('Withdrawn')).toBeInTheDocument();
    expect(screen.queryByRole('alertdialog')).toBeNull();
  });

  it('opens the alert of a withdrawal nobody answered', async () => {
    caseBookings.current = [STATE_WITHDRAWN];
    renderPanel();
    expect(await screen.findByRole('alertdialog')).toBeInTheDocument();
  });

  it('offers Request booking when the read fails: the back end refuses a second request itself (409)', async () => {
    server.use(http.get('/api/bff/bookings', () => HttpResponse.json({ code: 'unavailable' }, { status: 503 })));
    renderPanel();
    expect(await screen.findByRole('button', { name: 'Request booking' })).toBeInTheDocument();
  });

  it('does not offer Request booking while the read is out, so a reload cannot post a second request', async () => {
    let release: () => void = () => undefined;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    server.use(
      http.get('/api/bff/bookings', async () => {
        await gate;
        return HttpResponse.json({ bookings: [STATE_CONFIRMED] });
      }),
    );
    renderPanel();
    expect(screen.queryByRole('button', { name: 'Request booking' })).toBeNull();
    release();
    expect(await screen.findByText('Booked')).toBeInTheDocument();
  });
});
