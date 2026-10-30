'use client';

import { useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';
import { Banner } from '@/components/ui/Banner';
import { Button } from '@/components/ui/Button';
import { Chip } from '@/components/ui/Chip';
import { bffRequest } from '@/lib/reporter/browser';
import { clock } from '@/lib/reporter/times';
import styles from '@/components/reporter/Reporter.module.css';

// One booking request in the app (W36): confirm it, or decline it with a reason. A booking shows
// only the age band, the need and the urgency: the rest of the referral follows in the referral system. The
// decision is sent once per press; both buttons wait while it is in flight.

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

const REASONS: { code: Reason; label: string }[] = [
  { code: 'full', label: 'Full' },
  { code: 'outside-criteria', label: 'Outside criteria' },
  { code: 'staffing-or-transport', label: 'Staffing' },
  { code: 'other', label: 'Other' },
];

export function BookingDecision({ reference }: { reference: string }) {
  const router = useRouter();
  const [booking, setBooking] = useState<Booking | null>(null);
  const [failed, setFailed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [reason, setReason] = useState<Reason | null>(null);
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

  if (failed) return <main className={styles.page}><p>We could not load this booking. Try again shortly.</p></main>;
  if (booking === null) return <main className={styles.page}><p role="status">Opening the booking</p></main>;

  const current = outcome ?? booking.status;

  const decide = async (decision: 'confirm' | 'decline') => {
    if (busy) return;
    setBusy(true);
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
    setFailed(true);
    return undefined;
  };

  const confirmLabel = booking.multiService ? `Confirm booking for ${booking.service}` : 'Confirm booking';
  const phone = booking.spoaPhone === null ? null : booking.spoaPhone.replace(/\s+/g, '');

  if (current === 'expired') {
    return (
      <main className={styles.page}>
        <p>{`This request expired at ${clock(booking.replyBy)}. The coordination team will phone you if they still need you.`}</p>
      </main>
    );
  }
  if (current === 'confirmed') {
    return (
      <main className={styles.page}>
        <h1 className={styles.title}>Booked</h1>
        <p>{`Reference ${booking.reference}, ${booking.service}. Confirmed ${clock(confirmedAt ?? booking.confirmedAt)}. The advisor has been told.`}</p>
        <p>Referral details follow in the referral system.</p>
        {phone === null ? (
          <p>Something changed? Phone the coordination team.</p>
        ) : (
          <p>
            Something changed? Phone the coordination team on <a href={`tel:${phone}`}>{booking.spoaPhone}</a>.
          </p>
        )}
      </main>
    );
  }
  if (current === 'declined') {
    return (
      <main className={styles.page}>
        <h1 className={styles.title}>Declined</h1>
        <p>Declined. The advisor has been told.</p>
      </main>
    );
  }

  return (
    <main className={styles.page}>
      {booking.multiService ? <Banner tone="info" title={`${booking.service} only`} /> : null}
      <p className={styles.eyebrow}>{booking.service}</p>
      <h1 className={styles.title}>{`Booking request ${booking.reference}`}</h1>
      {booking.ageBand === null ? null : <p>{`Age band ${booking.ageBand}`}</p>}
      <p>{`Need ${booking.need}`}</p>
      {booking.urgency === null ? null : <p>{booking.urgency}</p>}
      <p>Referral details follow in the referral system.</p>
      <p className={styles.question}>Reply by {`${clock(booking.replyBy)}.`}</p>
      <Button variant="primary" busy={busy} dataEl="REP-BOOK-CONFIRM-BTN" onClick={() => void decide('confirm')}>
        {confirmLabel}
      </Button>
      <p className={styles.or}>Or decline. Why? (optional)</p>
      <div role="group" aria-label="Reason for declining">
        {REASONS.map((option) => (
          <Chip
            key={option.code}
            pressed={reason === option.code}
            onPressedChange={(next) => setReason(next ? option.code : null)}
            dataEl={`REP-BOOK-REASON-${option.code.toUpperCase()}`}
          >
            {option.label}
          </Chip>
        ))}
      </div>
      <Button variant="neutral" busy={busy} dataEl="REP-BOOK-DECLINE-BTN" onClick={() => void decide('decline')}>
        Decline
      </Button>
      {failed ? <Banner tone="warning" title="We could not send that. Try again." /> : null}
    </main>
  );
}
