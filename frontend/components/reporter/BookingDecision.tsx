'use client';

import { useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';
import { type BookingAnswer, type BookingOutcome, readLinkView, sendBookingAnswer } from '@/lib/links/browser';
import { type BookingView, type ClosedLink, londonHm } from '@/lib/links/model';
import { BookingDecisionView, type BookingNotice, type BookingScreen } from './booking/BookingDecisionView';
import { closedFacts } from './closed';
import { LinkUnavailable } from './LinkUnavailable';
import { LinkFrame } from './parts/LinkFrame';

// The service's page for a booking request (L02, W19; artboard B4). It opens from the request text or email.
// Opening it changes nothing: only a press posts. A confirm or a decline is single use, so once it
// is answered (or closed by the coordination team) the page shows what the booking now is, with the
// time and, for a closed request, the reference and the coordination number. The page itself is the shared
// BookingDecisionView in the link frame; this file reads the link and posts the answer.
//
// The link is read once (KI-651): a page that has already read it (LinkLoader) passes what it read, as
// `initial` (an open request) or `initialClosed` (a closed one), and this page reads nothing.

type Phase = 'loading' | 'open' | 'busy' | 'booked' | 'declined' | 'closed' | 'unavailable';

// The referral system is the tenant's own word (its profile); these two lines are the debt the guards count.
const REQUEST_NOTE = 'Referral details follow in SystmOne. No patient name is shown here.';
const BOOKED_NOTE = 'Referral details follow in SystmOne.';

const FAILED: BookingNotice = { tone: 'error', text: 'We could not record that. Try again.' };
const RATE_LIMITED: BookingNotice = { tone: 'warning', text: 'Too many tries. Wait a few minutes, then try again.' };

/** The page a refused answer (409) or a closed link shows, from the booking's state word. */
function pageFor(state: string): Phase {
  if (state === 'declined') return 'declined';
  if (state === 'confirmed') return 'booked';
  return 'closed';
}

const hm = (instant: string | null | undefined): string | null => (instant === null || instant === undefined ? null : londonHm(instant));

type Props = { token: string; initial?: BookingView; initialClosed?: ClosedLink };

export function BookingDecision({ token, initial, initialClosed }: Props) {
  const router = useRouter();
  const given = initial !== undefined || initialClosed !== undefined;
  const [phase, setPhase] = useState<Phase>(initial !== undefined ? 'open' : initialClosed !== undefined ? 'closed' : 'loading');
  const [view, setView] = useState<BookingView | null>(initial ?? null);
  // What the booking says of its closing, and the time of the answer this page took (or was refused with).
  const [closed, setClosed] = useState<ClosedLink | null>(initialClosed ?? null);
  const [when, setWhen] = useState<string | null>(null);
  const [changeToken, setChangeToken] = useState<string | null>(null);
  const [notice, setNotice] = useState<BookingNotice | null>(null);

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

  const phone = closed?.coordinationPhone ?? view?.coordinationPhone ?? null;
  const closedScreen: BookingScreen = {
    kind: 'closed',
    heading: 'This request has closed',
    detail: closedFacts(closed),
    phoneAsk: true,
  };

  let screen: BookingScreen;
  if (phase === 'closed') {
    screen = closedScreen;
  } else if (phase === 'loading' || view === null) {
    screen = { kind: 'loading', label: 'Opening your link.' };
  } else if (phase === 'booked') {
    screen = {
      kind: 'booked',
      reference: view.reference,
      service: view.serviceName,
      confirmedAt: hm(when),
      note: BOOKED_NOTE,
      changeHref: changeToken === null ? null : `/l/${changeToken}/booking/change`,
    };
  } else if (phase === 'declined') {
    screen = { kind: 'declined', reference: view.reference, declinedAt: hm(when) };
  } else {
    screen = {
      kind: 'request',
      reference: view.reference,
      service: view.serviceName,
      ageBand: view.ageBand,
      need: view.need,
      urgency: view.urgency,
      replyBy: view.replyBy === null ? null : londonHm(view.replyBy),
      onlyService: false,
      confirmLabel: 'Confirm booking',
      note: REQUEST_NOTE,
    };
  }

  // The tag says no login is needed while the person is still deciding; a result page leaves it out.
  const deciding = screen.kind === 'loading' || screen.kind === 'request';
  return (
    <LinkFrame noLoginTag={deciding}>
      <BookingDecisionView
        screen={screen}
        phone={phone}
        busy={phase === 'busy'}
        notice={notice}
        dataElPrefix="SVC-BOOK"
        onConfirm={() => void answer({ action: 'confirm' })}
        onDecline={(reason) => void answer(reason === null ? { action: 'decline' } : { action: 'decline', reason })}
      />
    </LinkFrame>
  );
}
