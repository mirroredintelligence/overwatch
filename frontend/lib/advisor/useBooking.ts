'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { readCsrfCookie } from './csrf';
import { type BookingState, type CancelReason, parseBookingState } from './bookings';

// One booking for one service, as the advisor's card keeps it (W20). The card never patches its state
// from an event: a `booking.updated` for this service means "read it again". A request is posted once
// per press, with an Idempotency-Key, and a second press while one is in flight does nothing.

/** The part of the browser's EventSource this hook uses. */
export type BookingStream = {
  addEventListener(type: string, listener: (event: MessageEvent) => void): void;
  close(): void;
};

export type BookingFetch = typeof fetch;

export type UseBookingOptions = {
  caseRef: string;
  serviceId: string;
  /** Opens the live stream (`/api/bff/events`) once a booking exists. Null or absent: no live updates. */
  openStream?: () => BookingStream | null;
  fetcher?: BookingFetch;
  /** Reads the booking again this often (ms), as a fallback to the stream. */
  pollMs?: number;
};

export type BookingController = {
  booking: BookingState | null;
  busy: boolean;
  /** The back end says this service already has a request waiting (409). */
  conflict: boolean;
  /** The request could not be sent, for a reason other than a waiting request. */
  failed: boolean;
  request: () => Promise<void>;
  /** A cancel is in flight. */
  cancelBusy: boolean;
  /** The booking moved on before the cancel (409): the card says so and reads the state again. */
  cancelConflict: boolean;
  cancel: (reason: CancelReason) => Promise<void>;
  /**
   * The advisor answered a withdrawal or not-reached alert (R17, DEC-854). True only when the back end
   * took the acknowledgement; anything else is false and the alert stays open. Posting twice is fine.
   */
  acknowledge: () => Promise<boolean>;
};

export const POLL_INTERVAL_MS = 30_000;
const BOOKING_EVENT = 'booking.updated';
const REQUEST_PATH = '/api/bff/bookings';

function keyForRequest(): string {
  return globalThis.crypto.randomUUID();
}

export function useBooking(options: UseBookingOptions): BookingController {
  const { caseRef, serviceId, openStream, pollMs = POLL_INTERVAL_MS } = options;
  const fetcher = useMemo<BookingFetch>(() => options.fetcher ?? ((input, init) => fetch(input, init)), [options.fetcher]);
  const [booking, setBooking] = useState<BookingState | null>(null);
  const [busy, setBusy] = useState(false);
  const [conflict, setConflict] = useState(false);
  const [failed, setFailed] = useState(false);
  const [cancelBusy, setCancelBusy] = useState(false);
  const [cancelConflict, setCancelConflict] = useState(false);
  const inFlight = useRef(false);
  const latest = useRef<BookingState | null>(null);
  useEffect(() => {
    latest.current = booking;
  }, [booking]);

  const read = useCallback(async () => {
    const current = latest.current;
    if (current === null) return;
    try {
      const response = await fetcher(`${REQUEST_PATH}/${encodeURIComponent(current.id)}`, {
        method: 'GET',
        cache: 'no-store',
        credentials: 'same-origin',
      });
      if (response.ok) setBooking(parseBookingState(await response.json()));
    } catch {
      // Keep the last state. The next read, the event or the poll tries again.
    }
  }, [fetcher]);

  const request = useCallback(async () => {
    if (inFlight.current || latest.current !== null) return;
    inFlight.current = true;
    setBusy(true);
    setConflict(false);
    setFailed(false);
    try {
      const response = await fetcher(REQUEST_PATH, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Idempotency-Key': keyForRequest(),
          'X-CSRF-Token': readCsrfCookie() ?? '',
        },
        body: JSON.stringify({ caseRef, serviceId }),
        cache: 'no-store',
        credentials: 'same-origin',
      });
      if (response.status === 201) {
        setBooking(parseBookingState(await response.json()));
      } else if (response.status === 409) {
        setConflict(true);
      } else {
        setFailed(true);
      }
    } catch {
      setFailed(true);
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  }, [caseRef, serviceId, fetcher]);

  const cancel = useCallback(
    async (reason: CancelReason) => {
      const current = latest.current;
      if (current === null || cancelBusy) return;
      setCancelBusy(true);
      setCancelConflict(false);
      try {
        const response = await fetcher(`${REQUEST_PATH}/${encodeURIComponent(current.id)}/cancel`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Idempotency-Key': keyForRequest(),
            'X-CSRF-Token': readCsrfCookie() ?? '',
          },
          body: JSON.stringify({ reason }),
          cache: 'no-store',
          credentials: 'same-origin',
        });
        if (response.status === 409) setCancelConflict(true);
        await read();
      } catch {
        // The cancel did not reach an answer: read the booking, so the card shows what the back end holds.
        setCancelConflict(true);
        await read();
      } finally {
        setCancelBusy(false);
      }
    },
    [cancelBusy, fetcher, read],
  );

  const acknowledge = useCallback(async () => {
    const current = latest.current;
    if (current === null) return false;
    try {
      const response = await fetcher(`${REQUEST_PATH}/${encodeURIComponent(current.id)}/acknowledge`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Idempotency-Key': keyForRequest(), 'X-CSRF-Token': readCsrfCookie() ?? '' },
        body: '{}',
        cache: 'no-store',
        credentials: 'same-origin',
      });
      return response.ok;
    } catch {
      // Not sent: the alert stays open and says so, and the back end keeps the escalation running.
      return false;
    }
  }, [fetcher]);

  // Live updates and the fallback poll run only while there is a booking to watch.
  const bookingId = booking?.id ?? null;
  useEffect(() => {
    if (bookingId === null) return;
    const stream = openStream?.() ?? null;
    stream?.addEventListener(BOOKING_EVENT, (event) => {
      let named: unknown;
      try {
        named = JSON.parse(String(event.data)) as unknown;
      } catch {
        return;
      }
      if (typeof named === 'object' && named !== null && (named as { serviceId?: unknown }).serviceId === serviceId) {
        void read();
      }
    });
    const timer = setInterval(() => void read(), pollMs);
    return () => {
      clearInterval(timer);
      stream?.close();
    };
    // The stream is opened once per booking; the callbacks it needs are read from refs above.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bookingId, serviceId, pollMs]);

  return { booking, busy, conflict, failed, request, cancelBusy, cancelConflict, cancel, acknowledge };
}
