'use client';

import { useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';
import { bffRequest } from '@/lib/reporter/browser';
import { clock } from '@/lib/reporter/times';
import { BookingDecisionView, type BookingNotice, type BookingScreen } from '../booking/BookingDecisionView';

// One booking request in the app (W36; artboard B4): confirm it, or decline it with a reason. A booking shows
// only the age band, the need and the urgency: the rest of the referral follows in the referral system. The
// decision is sent once per press; every button waits while it is in flight. The page is the shared
// BookingDecisionView; the installed app's frame is the /app layout's, so it is not drawn again here.

type Reason = 'full' | 'outside-criteria' | 'staffing-or-transport' | 'other';
type Status = 'requested' | 'confirmed' | 'declined' | 'expired';

// What the BFF gives (the back end's booking by its reference, DEC-821): the instants are ISO, the age
// band, the urgency and the coordination number may be absent, and nothing of the case is in it.
type Booking = {
  reference: string;
  service: string;
  ageBand: string | null;
  need: string;
  urgency: string | null;
  replyBy: string;
  status: Status;
  multiService: boolean;
  confirmedAt?: string;
  spoaPhone: string | null;
};

const STATUSES: readonly string[] = ['requested', 'confirmed', 'declined', 'expired'];

function readBooking(body: unknown): Booking | null {
  const v = body as Partial<Booking> | undefined;
  if (typeof v?.reference !== 'string' || typeof v.service !== 'string' || typeof v.need !== 'string' || typeof v.replyBy !== 'string') return null;
  if (typeof v.status !== 'string' || !STATUSES.includes(v.status) || typeof v.multiService !== 'boolean') return null;
  return {
    reference: v.reference,
    service: v.service,
    ageBand: typeof v.ageBand === 'string' ? v.ageBand : null,
    need: v.need,
    urgency: typeof v.urgency === 'string' ? v.urgency : null,
    replyBy: v.replyBy,
    status: v.status as Status,
    multiService: v.multiService,
    spoaPhone: typeof v.spoaPhone === 'string' ? v.spoaPhone : null,
    ...(typeof v.confirmedAt === 'string' ? { confirmedAt: v.confirmedAt } : {}),
  };
}

const NOT_SENT: BookingNotice = { tone: 'error', text: 'We could not send that. Try again.' };

export function BookingDecision({ reference }: { reference: string }) {
  const router = useRouter();
  const [booking, setBooking] = useState<Booking | null>(null);
  const [failed, setFailed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<BookingNotice | null>(null);
  const [outcome, setOutcome] = useState<Status | null>(null);
  const [confirmedAt, setConfirmedAt] = useState<string | undefined>(undefined);
  const [key] = useState(() => crypto.randomUUID());

  useEffect(() => {
    let live = true;
    void bffRequest(`/api/bff/reporter/bookings/${encodeURIComponent(reference)}`).then((reply) => {
      if (!live) return;
      if (reply.status === 401) return router.replace('/app/pin');
      const read = reply.status === 200 ? readBooking(reply.body) : null;
      if (read === null) return setFailed(true);
      setBooking(read);
    });
    return () => {
      live = false;
    };
  }, [reference, router]);

  const decide = async (decision: 'confirm' | 'decline', reason: Reason | null) => {
    if (busy) return;
    setBusy(true);
    setNotice(null);
    const body = decision === 'decline' && reason !== null ? { decision, reason } : { decision };
    const reply = await bffRequest(`/api/bff/reporter/bookings/${encodeURIComponent(reference)}/respond`, {
      method: 'POST',
      body,
      headers: { 'Idempotency-Key': key },
    });
    setBusy(false);
    if (reply.status === 401) return router.replace('/app/pin');
    const answer = reply.body as { status?: string; confirmedAt?: string } | undefined;
    if (reply.status === 409) {
      // Answered meanwhile (by someone else, or the time ran out): show what the back end holds.
      const fresh = await bffRequest(`/api/bff/reporter/bookings/${encodeURIComponent(reference)}`);
      const read = fresh.status === 200 ? readBooking(fresh.body) : null;
      if (read === null || read.status === 'requested') return setFailed(true);
      setBooking(read);
      setOutcome(null);
      return undefined;
    }
    if (reply.status === 200 && answer?.status === 'confirmed') {
      setConfirmedAt(answer.confirmedAt);
      return setOutcome('confirmed');
    }
    if (reply.status === 200 && answer?.status === 'declined') return setOutcome('declined');
    // Nothing was recorded: the request stays, with the same key, so the person can press again.
    setNotice(NOT_SENT);
    return undefined;
  };

  let screen: BookingScreen;
  let phone: string | null = null;
  if (failed) {
    screen = { kind: 'failed', lead: 'We could not load this booking.', text: 'Try again shortly.' };
  } else if (booking === null) {
    screen = { kind: 'loading', label: 'Opening the booking.' };
  } else {
    phone = booking.spoaPhone;
    const current = outcome ?? booking.status;
    if (current === 'expired') {
      screen = {
        kind: 'closed',
        heading: 'This request has expired',
        detail: `This request expired at ${clock(booking.replyBy)}. The coordination team will phone you if they still need you.`,
        phoneAsk: false,
      };
    } else if (current === 'confirmed') {
      const at = clock(confirmedAt ?? booking.confirmedAt);
      screen = {
        kind: 'booked',
        reference: booking.reference,
        service: booking.service,
        confirmedAt: at === '' ? null : at,
        note: 'Referral details follow in the referral system.',
        changeHref: null,
      };
    } else if (current === 'declined') {
      screen = { kind: 'declined', reference: booking.reference, declinedAt: null };
    } else {
      screen = {
        kind: 'request',
        reference: booking.reference,
        service: booking.service,
        ageBand: booking.ageBand,
        need: booking.need,
        urgency: booking.urgency,
        replyBy: clock(booking.replyBy),
        onlyService: booking.multiService,
        confirmLabel: booking.multiService ? `Confirm booking for ${booking.service}` : 'Confirm booking',
        note: 'Referral details follow in the referral system. No patient name is shown here.',
      };
    }
  }

  return (
    <BookingDecisionView
      screen={screen}
      phone={phone}
      busy={busy}
      notice={notice}
      dataElPrefix="REP-BOOK"
      onConfirm={() => void decide('confirm', null)}
      onDecline={(reason) => void decide('decline', reason as Reason | null)}
    />
  );
}
