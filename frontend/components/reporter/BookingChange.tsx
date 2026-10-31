'use client';

import { useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';
import { Banner } from '@/components/ui/Banner';
import { Button } from '@/components/ui/Button';
import { OptionButton } from '@/components/ui/OptionButton';
import { type BookingAnswer, type BookingOutcome, readLinkView, sendBookingAnswer } from '@/lib/links/browser';
import { type BookingView, type ClosedLink, londonHm } from '@/lib/links/model';
import { atTime, closedFacts, PhoneTo } from './closed';
import { LinkUnavailable } from './LinkUnavailable';
import styles from './Reporter.module.css';

// The service's page for a confirmed booking that changes (L02, W22): withdraw it, or report the
// patient was not reached. The views are steps in one page; Back returns to the booked view. Only
// a press posts, and a change is single use, so a refused one shows the booking's final state.

type Step =
  | 'loading'
  | 'booked'
  | 'withdraw'
  | 'not-reached'
  | 'withdrawn'
  | 'thanks'
  | 'cancelled'
  | 'closed'
  | 'unavailable';

const WITHDRAW_REASONS = [
  { code: 'now-full', label: 'We are now full', dataEl: 'SVC-WITHDRAW-REASON-FULL' },
  { code: 'staffing', label: 'Staffing', dataEl: 'SVC-WITHDRAW-REASON-STAFFING' },
  { code: 'cannot-reach-patient', label: 'We cannot reach the patient', dataEl: 'SVC-WITHDRAW-REASON-REACH' },
  { code: 'other', label: 'Other', dataEl: 'SVC-WITHDRAW-REASON-OTHER' },
] as const;

const NOT_REACHED_REASONS = [
  { code: 'not-at-address', label: 'Not at the address', dataEl: 'SVC-NOTREACHED-REASON-ADDRESS' },
  { code: 'no-answer', label: 'No answer at the door', dataEl: 'SVC-NOTREACHED-REASON-NOANSWER' },
  { code: 'gone-to-hospital', label: 'Gone to hospital', dataEl: 'SVC-NOTREACHED-REASON-HOSPITAL' },
  { code: 'other', label: 'Other', dataEl: 'SVC-NOTREACHED-REASON-OTHER' },
] as const;

const FAILED = 'We could not record that. Try again.';
const RATE_LIMITED = 'Too many tries. Wait a few minutes, then try again.';

/** The step a refused change (409) or a closed link shows, from the booking's state word. */
function stepFor(state: string): Step {
  if (state === 'withdrawn') return 'withdrawn';
  if (state === 'not-reached') return 'thanks';
  if (state === 'cancelled') return 'cancelled';
  return 'closed';
}

function capitalise(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

// The link is read once (KI-651): a page that has already read it (LinkLoader) passes what it read, as
// `initial` (an open change link) or `initialClosed` (a closed one), and this page reads nothing.
type Props = { token: string; initial?: BookingView; initialClosed?: ClosedLink };

function stepForClosed(state: string): Step {
  return state === 'cancelled' ? 'cancelled' : state === 'withdrawn' ? 'withdrawn' : state === 'not-reached' ? 'thanks' : 'closed';
}

export function BookingChange({ token, initial, initialClosed }: Props) {
  const router = useRouter();
  const given = initial !== undefined || initialClosed !== undefined;
  const [step, setStep] = useState<Step>(
    initial !== undefined ? 'booked' : initialClosed !== undefined ? stepForClosed(initialClosed.state) : 'loading',
  );
  const [view, setView] = useState<BookingView | null>(initial ?? null);
  // What the booking says of its closing, and the time of the change this page took (or was refused with).
  const [closed, setClosed] = useState<ClosedLink | null>(initialClosed ?? null);
  const [when, setWhen] = useState<string | null>(null);
  const [reason, setReason] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [closing, setClosing] = useState(false);
  const [redirect, setRedirect] = useState<string | null>(null);

  useEffect(() => {
    if (given) return undefined;
    let current = true;
    void readLinkView(token).then((result) => {
      if (!current) return;
      if (result.kind === 'booking' && result.view.purpose === 'booking-change') {
        setView(result.view);
        setStep('booked');
        return;
      }
      if (result.kind === 'booking') {
        setRedirect(`/l/${token}/booking`);
        return;
      }
      if (result.kind === 'open') {
        setRedirect(`/l/${token}`);
        return;
      }
      if (result.kind === 'gone') {
        setClosed(result.closed);
        setStep(stepForClosed(result.closed.state));
        return;
      }
      setStep('unavailable');
    });
    return () => {
      current = false;
    };
  }, [token, given]);

  useEffect(() => {
    if (redirect !== null) router.replace(redirect);
  }, [redirect, router]);

  // Going into a form adds a history entry, so the browser's Back button returns to the booked view.
  // The entry keeps whatever state the router put on it.
  function enter(next: Step) {
    setNotice(null);
    setReason(null);
    window.history.pushState({ ...(window.history.state as object | null), diucsStep: next }, '');
    setStep(next);
  }

  useEffect(() => {
    const onPop = () => {
      setStep((current) => (current === 'withdraw' || current === 'not-reached' ? 'booked' : current));
    };
    window.addEventListener('popstate', onPop);
    return () => window.removeEventListener('popstate', onPop);
  }, []);

  async function answer(next: BookingAnswer) {
    if (view === null) return;
    setBusy(true);
    setNotice(null);
    const outcome: BookingOutcome = await sendBookingAnswer(token, view.csrfToken, next);
    setBusy(false);
    switch (outcome.kind) {
      case 'answered':
        setWhen(outcome.respondedAt ?? null);
        setStep(outcome.bookingStatus === 'withdrawn' ? 'withdrawn' : 'thanks');
        return;
      case 'conflict':
        setClosed(outcome.closed);
        setWhen(outcome.closed.closedAt);
        setStep(stepFor(outcome.state));
        return;
      case 'gone':
        setClosed(outcome.closed);
        setStep('closed');
        return;
      case 'rate-limited':
        setNotice(RATE_LIMITED);
        return;
      default:
        setNotice(FAILED);
    }
  }

  if (step === 'unavailable') return <LinkUnavailable />;

  const closeNote = closing ? <p className={styles.footer}>You can close this page.</p> : null;
  const closeButton = (
    <Button variant="neutral" dataEl="SVC-CHANGE-CLOSE-BTN" onClick={() => setClosing(true)}>
      Close
    </Button>
  );

  if (step === 'loading') {
    return (
      <main className={styles.page}>
        <p className={styles.eyebrow} role="status">
          Opening your link…
        </p>
      </main>
    );
  }

  const knownPhone = closed?.coordinationPhone ?? view?.coordinationPhone ?? null;

  if (step === 'closed') {
    const facts = closedFacts(closed);
    return (
      <main className={styles.page}>
        <p className={styles.eyebrow}>DIUCS booking</p>
        <h1 className={styles.title}>This link has closed</h1>
        <p className={styles.question}>This link can no longer be used.</p>
        {facts !== null ? <p className={styles.or}>{facts}</p> : null}
        <p className={styles.footer}>You can close this page.</p>
      </main>
    );
  }

  if (step === 'cancelled') {
    return (
      <main className={styles.page}>
        <p className={styles.eyebrow}>Cancelled</p>
        <h1 className={styles.title}>Cancelled by the coordination team</h1>
        <p className={styles.question}>
          {closed?.reference != null && closed.cancelledAt !== null
            ? `Booking ${closed.reference} was cancelled at ${londonHm(closed.cancelledAt)}. No action needed.`
            : 'The booking was cancelled by the coordination team. No action needed.'}
        </p>
        {knownPhone !== null ? (
          <p className={styles.footer}>
            <PhoneTo phone={knownPhone} lead="If the patient has already been told you are coming, phone the coordination team on" none="" />
          </p>
        ) : null}
        {closeButton}
        {closeNote}
      </main>
    );
  }

  if (step === 'withdrawn') {
    const phone = knownPhone;
    return (
      <main className={styles.page}>
        <p className={styles.eyebrow}>Withdrawn</p>
        <h1 className={styles.title}>Withdrawn</h1>
        <p className={styles.question}>The coordination team has been told and is finding another service.</p>
        {atTime('Withdrawn', when) !== null ? <p className={styles.or}>{atTime('Withdrawn', when)}</p> : null}
        <p className={styles.footer}>
          {phone === null ? (
            'If the patient has already been told you are coming, phone the coordination team now.'
          ) : (
            <>If the patient has already been told you are coming, phone the coordination team on <a href={`tel:${phone}`}>{phone}</a> now.</>
          )}
        </p>
        {closeButton}
        {closeNote}
      </main>
    );
  }

  if (step === 'thanks') {
    return (
      <main className={styles.page}>
        <p className={styles.eyebrow}>Not reached</p>
        <h1 className={styles.title}>Thank you</h1>
        <p className={styles.question}>The coordination team has been told.</p>
        {atTime('Recorded', when) !== null ? <p className={styles.or}>{atTime('Recorded', when)}</p> : null}
        {closeButton}
        {closeNote}
      </main>
    );
  }

  if (view === null) return null;
  const busyNow = busy;

  if (step === 'withdraw') {
    return (
      <main className={styles.page}>
        <p className={styles.eyebrow}>Withdraw</p>
        <h2 className={styles.title}>Why can you no longer take this patient?</h2>
        <div role="group" aria-label="Why can you no longer take this patient?">
          {WITHDRAW_REASONS.map((option) => (
            <OptionButton
              key={option.code}
              selected={reason === option.code}
              dataEl={option.dataEl}
              onSelect={() => setReason(option.code)}
            >
              {option.label}
            </OptionButton>
          ))}
        </div>
        <p className={styles.footer}>The coordination team is told at once and will find another service. The patient will not be left without a plan.</p>
        <Button
          variant="primary"
          busy={busyNow}
          disabled={reason === null}
          dataEl="SVC-WITHDRAW-SUBMIT-BTN"
          onClick={() => reason !== null && answer({ action: 'withdraw', reason })}
        >
          Withdraw booking
        </Button>
        <Button variant="neutral" disabled={busyNow} dataEl="SVC-CHANGE-BACK-BTN" onClick={() => setStep('booked')}>
          Back
        </Button>
        {notice !== null ? <Banner tone="warning" title={notice} dataEl="SVC-CHANGE-NOTICE" /> : null}
      </main>
    );
  }

  if (step === 'not-reached') {
    return (
      <main className={styles.page}>
        <p className={styles.eyebrow}>Not reached</p>
        <h2 className={styles.title}>Patient not found or not there</h2>
        <div role="group" aria-label="Patient not found or not there">
          {NOT_REACHED_REASONS.map((option) => (
            <OptionButton
              key={option.code}
              selected={reason === option.code}
              dataEl={option.dataEl}
              onSelect={() => setReason(option.code)}
            >
              {option.label}
            </OptionButton>
          ))}
        </div>
        <p className={styles.footer}>The coordination team is told and will phone the caller.</p>
        <Button
          variant="primary"
          busy={busyNow}
          disabled={reason === null}
          dataEl="SVC-NOTREACHED-SAVE-BTN"
          onClick={() => reason !== null && answer({ action: 'not-reached', reason })}
        >
          Save
        </Button>
        <Button variant="neutral" disabled={busyNow} dataEl="SVC-CHANGE-BACK-BTN" onClick={() => setStep('booked')}>
          Back
        </Button>
        {notice !== null ? <Banner tone="warning" title={notice} dataEl="SVC-CHANGE-NOTICE" /> : null}
      </main>
    );
  }

  // The booked view.
  const rows = [
    view.ageBand === null ? null : `Age band ${view.ageBand}`,
    view.need === null ? null : `Need ${view.need}`,
    view.urgency === null ? null : `Wanted ${capitalise(view.urgency)}`,
  ].filter((row): row is string => row !== null);

  return (
    <main className={styles.page}>
      <p className={styles.eyebrow}>{`Booking ${view.reference}`}</p>
      <p className={styles.question}>Booked</p>
      <h1 className={styles.title}>{view.serviceName}</h1>
      {atTime('Confirmed', view.confirmedAt) !== null ? <p className={styles.or}>{atTime('Confirmed', view.confirmedAt)}</p> : null}
      <p className={styles.or}>Referral details follow in SystmOne.</p>
      {rows.map((row) => (
        <p key={row} className={styles.question}>
          {row}
        </p>
      ))}
      <p className={styles.footer}>Something changed? Tell us here so the coordination team can act at once.</p>
      <Button variant="secondary" disabled={busyNow} dataEl="SVC-CHANGE-WITHDRAW-BTN" onClick={() => enter('withdraw')}>
        We cannot take this patient now
      </Button>
      <Button variant="secondary" disabled={busyNow} dataEl="SVC-CHANGE-NOTREACHED-BTN" onClick={() => enter('not-reached')}>
        Patient not found or not there
      </Button>
      {closeButton}
      {closeNote}
    </main>
  );
}
