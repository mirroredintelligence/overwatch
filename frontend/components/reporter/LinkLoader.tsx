'use client';

import { useEffect, useState } from 'react';
import { readLinkView } from '@/lib/links/browser';
import type { BookingView, ClosedLink, LinkView } from '@/lib/links/model';
import { BookingChange } from './BookingChange';
import { BookingDecision } from './BookingDecision';
import { CapacityResponder } from './CapacityResponder';
import { LinkExpired } from './LinkExpired';
import { LinkUnavailable } from './LinkUnavailable';
import styles from './Reporter.module.css';

// Reads the link once through the BFF (which sets its CSRF cookie) and shows what it says: the
// capacity page, the booking request or change page, the closed page, or the unavailable page. A booking
// page is shown here with the view this read gave it, so the link is read once (KI-651, DEC-167 item 8).
// Nothing is posted here; only a press in the page posts.

type State =
  | { kind: 'loading' }
  | { kind: 'open'; view: LinkView }
  | { kind: 'booking'; view: BookingView }
  | { kind: 'gone'; closed: ClosedLink; csrfToken: string | null }
  | { kind: 'unavailable' };

const CHANGE_PURPOSE = 'booking-change';
/** The states only a change link has: a booking cancelled, withdrawn or reported not reached. */
const CHANGE_STATES: readonly string[] = ['cancelled', 'withdrawn', 'not-reached'];

export function LinkLoader({ token }: { token: string }) {
  const [state, setState] = useState<State>({ kind: 'loading' });

  useEffect(() => {
    let current = true;
    void readLinkView(token).then((result) => {
      if (!current) return;
      setState(result);
    });
    return () => {
      current = false;
    };
  }, [token]);

  switch (state.kind) {
    case 'loading':
      return (
        <main className={styles.page}>
          <p className={styles.eyebrow} role="status">
            Opening your link…
          </p>
        </main>
      );
    case 'open':
      return <CapacityResponder token={token} view={state.view} />;
    case 'booking':
      return state.view.purpose === CHANGE_PURPOSE ? (
        <BookingChange token={token} initial={state.view} />
      ) : (
        <BookingDecision token={token} initial={state.view} />
      );
    case 'gone':
      if (state.closed.kind === 'booking') {
        return CHANGE_STATES.includes(state.closed.state) ? (
          <BookingChange token={token} initialClosed={state.closed} />
        ) : (
          <BookingDecision token={token} initialClosed={state.closed} />
        );
      }
      return <LinkExpired token={token} csrfToken={state.csrfToken} />;
    case 'unavailable':
      return <LinkUnavailable />;
  }
}
