import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { FakeStream } from '@/test/fakeStream';
import { runAxe } from '@/test/a11y';
import { BOOKING_ID, CASE_REF, SERVICE_ID, SERVICE_PHONE, SERVICE_WITH_OPEN_REQUEST, STATE_CONFIRMED } from '@/test/fixtures/bookings';
import { bookingStore, resetBookingRequests, seenBookingPosts, seenBookingReads } from '@/test/msw/handlers/bookings';
import { BookingPanel } from './BookingPanel';

// The "Request booking" control and the booking card it opens (W20). The live stream and the
// clock are the test's: a FakeStream stands for /api/bff/events, and the card's timers are fake.

const CSRF = 'csrf-value-for-the-panel';

function setCsrfCookie() {
  document.cookie = `diucs_csrf=${CSRF}; path=/`;
}

let stream: FakeStream;

function renderPanel(serviceId = SERVICE_ID) {
  return render(
    <BookingPanel
      caseRef={CASE_REF}
      serviceId={serviceId}
      serviceName="UCR West"
      servicePhone={SERVICE_PHONE}
      openStream={() => {
        stream = new FakeStream();
        return stream;
      }}
    />,
  );
}

beforeEach(() => {
  resetBookingRequests();
  setCsrfCookie();
  vi.useRealTimers();
});

describe('BookingPanel: Request booking', () => {
  it('posts once with the CSRF header and an Idempotency-Key, then shows the requested text with 14:21 and 14:26', async () => {
    const { container } = renderPanel();
    await userEvent.click(screen.getByRole('button', { name: 'Request booking' }));
    expect(await screen.findByText('Text sent 14:16. Waiting for CONFIRMED. Phone prompt at 14:21. Request expires 14:26.')).toBeInTheDocument();
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
