'use client';

import { useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';
import { Banner } from '@/components/ui/Banner';
import { Button } from '@/components/ui/Button';
import { Chip } from '@/components/ui/Chip';
import { type BookingAnswer, type BookingOutcome, readLinkView, sendBookingAnswer } from '@/lib/links/browser';
import { type BookingView, type ClosedLink, londonHm } from '@/lib/links/model';
import { atTime, closedFacts, PhoneTo } from './closed';
import { LinkUnavailable } from './LinkUnavailable';
import styles from './Reporter.module.css';

// The service's page for a booking request (L02, W19). It opens from the request text or email.
// Opening it changes nothing: only a press posts. A confirm or a decline is single use, so once it
// is answered (or closed by the coordination team) the page shows what the booking now is, with the
// time and, for a closed request, the reference and the coordination number.
//
// The link is read once (KI-651): a page that has already read it (LinkLoader) passes what it read, as
// `initial` (an open request) or `initialClosed` (a closed one), and this page reads nothing.

type Phase = 'loading' | 'open' | 'busy' | 'booked' | 'declined' | 'closed' | 'unavailable';

const REASONS = [
  { code: 'full', label: 'We are full', dataEl: 'SVC-BOOK-REASON-FULL' },
  { code: 'outside-criteria', label: 'Outside our criteria', dataEl: 'SVC-BOOK-REASON-OUTSIDE' },
  { code: 'staffing-or-transport', label: 'Staffing or transport', dataEl: 'SVC-BOOK-REASON-STAFFING' },
  { code: 'other', label: 'Other', dataEl: 'SVC-BOOK-REASON-OTHER' },
] as const;

const FAILED = 'We could not record that. Try again.';
const RATE_LIMITED = 'Too many tries. Wait a few minutes, then try again.';

/** The page a refused answer (409) or a closed link shows, from the booking's state word. */
function pageFor(state: string): Phase {
  if (state === 'declined') return 'declined';
  if (state === 'confirmed') return 'booked';
  return 'closed';
}

function capitalise(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

type Props = { token: string; initial?: BookingView; initialClosed?: ClosedLink };

export function BookingDecision({ token, initial, initialClosed }: Props) {
  const router = useRouter();
  const given = initial !== undefined || initialClosed !== undefined;
  const [phase, setPhase] = useState<Phase>(initial !== undefined ? 'open' : initialClosed !== undefined ? 'closed' : 'loading');
  const [view, setView] = useState<BookingView | null>(initial ?? null);
  // What the booking says of its closing, and the time of the answer this page took (or was refused with).
  const [closed, setClosed] = useState<ClosedLink | null>(initialClosed ?? null);
  const [when, setWhen] = useState<string | null>(null);
  const [reason, setReason] = useState<string | null>(null);
  const [changeToken, setChangeToken] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  // The link is read once per token. A redirect is kept in state and taken by its own effect, so a
  // router that is not the same object on each render cannot make the page read the link again.
  const [redirect, setRedirect] = useState<string | null>(null);

  useEffect(() => {
    if (given) return undefined;
    let current = true;
    void readLinkView(token).then((result) => {
      if (!current) return;
      if (result.kind === 'booking' && result.view.purpose === 'booking-request') {
        setView(result.view);
        setPhase('open');
        return;
      }
      if (result.kind === 'booking') {
        setRedirect(`/l/${token}/booking/change`);
        return;
      }
      if (result.kind === 'open') {
        setRedirect(`/l/${token}`);
        return;
      }
      if (result.kind === 'gone') setClosed(result.closed);
      setPhase(result.kind === 'gone' ? 'closed' : 'unavailable');
    });
    return () => {
      current = false;
    };
  }, [token, given]);

  useEffect(() => {
    if (redirect !== null) router.replace(redirect);
  }, [redirect, router]);

  async function answer(next: BookingAnswer) {
    if (view === null) return;
    setPhase('busy');
    setNotice(null);
    const outcome: BookingOutcome = await sendBookingAnswer(token, view.csrfToken, next);
    switch (outcome.kind) {
      case 'answered':
        if (outcome.bookingStatus === 'declined') {
          setWhen(outcome.respondedAt ?? null);
          setPhase('declined');
        } else {
          setWhen(outcome.confirmedAt ?? null);
          setChangeToken(outcome.changeToken ?? null);
          setPhase('booked');
        }
        return;
      case 'conflict':
        setClosed(outcome.closed);
        setWhen(outcome.state === 'confirmed' ? outcome.closed.confirmedAt : outcome.closed.closedAt);
        setPhase(pageFor(outcome.state));
        return;
      case 'gone':
        setClosed(outcome.closed);
        setPhase('closed');
        return;
      case 'rate-limited':
        setPhase('open');
        setNotice(RATE_LIMITED);
        return;
      default:
        setPhase('open');
        setNotice(FAILED);
    }
  }

  if (phase === 'unavailable') return <LinkUnavailable />;

  if (phase === 'loading' || view === null) {
    if (phase === 'closed') return <Closed closed={closed} phone={closed?.coordinationPhone ?? null} />;
    return (
      <main className={styles.page}>
        <p className={styles.eyebrow} role="status">
          Opening your link…
        </p>
      </main>
    );
  }

  const phone = closed?.coordinationPhone ?? view.coordinationPhone;

  if (phase === 'closed') return <Closed closed={closed} phone={phone} />;

  if (phase === 'booked') {
    return (
      <main className={styles.page}>
        <p className={styles.eyebrow}>DIUCS booking request</p>
        <h1 className={styles.title}>Booked</h1>
        <p className={styles.question}>{`Reference ${view.reference}, ${view.serviceName}. The advisor has been told.`}</p>
        {atTime('Confirmed', when) !== null ? <p className={styles.or}>{atTime('Confirmed', when)}</p> : null}
        <p className={styles.or}>Referral details follow in SystmOne.</p>
        <p className={styles.footer}>
          Something changed?{' '}
          {phone === null ? 'Phone the coordination team.' : <>Phone the coordination team on <a href={`tel:${phone}`}>{phone}</a>.</>}
        </p>
        {changeToken !== null ? (
          <a href={`/l/${changeToken}/booking/change`} data-el="SVC-BOOK-CHANGE-LINK">
            Tell us something changed
          </a>
        ) : null}
        <p className={styles.footer}>You can close this page.</p>
      </main>
    );
  }

  if (phase === 'declined') {
    return (
      <main className={styles.page}>
        <p className={styles.eyebrow}>DIUCS booking request</p>
        <h1 className={styles.title}>Declined</h1>
        <p className={styles.question}>{`Reference ${view.reference} declined. The advisor has been told.`}</p>
        {atTime('Declined', when) !== null ? <p className={styles.or}>{atTime('Declined', when)}</p> : null}
        <p className={styles.footer}>You can close this page.</p>
      </main>
    );
  }

  const busy = phase === 'busy';
  const rows = [
    view.ageBand === null ? null : `Age band ${view.ageBand}`,
    view.need === null ? null : `Need ${view.need}`,
    view.urgency === null ? null : `Response wanted ${capitalise(view.urgency)}`,
  ].filter((row): row is string => row !== null);

  return (
    <main className={styles.page}>
      <p className={styles.eyebrow}>{`DIUCS booking request · Reference ${view.reference}`}</p>
      <h1 className={styles.title}>{view.serviceName}</h1>
      {rows.map((row) => (
        <p key={row} className={styles.question}>
          {row}
        </p>
      ))}
      <p className={styles.or}>Referral details follow in SystmOne.</p>

      <Button variant="primary" busy={busy} dataEl="SVC-BOOK-CONFIRM-BTN" onClick={() => answer({ action: 'confirm' })}>
        Confirm booking
      </Button>

      <p className={styles.or}>Or decline. Why? (optional)</p>
      <div role="group" aria-label="Why are you declining? (optional)">
        {REASONS.map((option) => (
          <Chip
            key={option.code}
            pressed={reason === option.code}
            dataEl={option.dataEl}
            onPressedChange={(next) => setReason(next ? option.code : null)}
          >
            {option.label}
          </Chip>
        ))}
      </div>
      <Button
        variant="secondary"
        busy={busy}
        dataEl="SVC-BOOK-DECLINE-BTN"
        onClick={() => answer(reason === null ? { action: 'decline' } : { action: 'decline', reason })}
      >
        Decline
      </Button>

      {notice !== null ? <Banner tone="warning" title={notice} dataEl="SVC-BOOK-NOTICE" /> : null}

      <p className={styles.footer}>
        {view.replyBy === null ? 'Not booked until you confirm.' : `Not booked until you confirm. Reply by ${londonHm(view.replyBy)}.`}
      </p>
    </main>
  );
}

function Closed({ closed, phone }: { closed: ClosedLink | null; phone: string | null }) {
  const facts = closedFacts(closed);
  return (
    <main className={styles.page}>
      <p className={styles.eyebrow}>DIUCS booking request</p>
      <h1 className={styles.title}>This request has closed</h1>
      {facts !== null ? <p className={styles.or}>{facts}</p> : null}
      <p className={styles.question}>
        <PhoneTo
          phone={phone}
          lead="If you can still take this patient, phone the coordination team on"
          none="If you can still take this patient, phone the coordination team."
        />
      </p>
    </main>
  );
}
