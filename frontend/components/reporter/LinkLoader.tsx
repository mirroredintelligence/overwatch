'use client';

import { useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';
import { readLinkView } from '@/lib/links/browser';
import type { LinkView } from '@/lib/links/model';
import { CapacityResponder } from './CapacityResponder';
import { LinkExpired } from './LinkExpired';
import { LinkUnavailable } from './LinkUnavailable';
import styles from './Reporter.module.css';

// Reads the link once through the BFF (which sets its CSRF cookie) and shows what it says: the
// capacity page, the expired page, the unavailable page, or the booking page for a booking link.
// Nothing is posted here; only a press in CapacityResponder posts.

type State =
  | { kind: 'loading' }
  | { kind: 'open'; view: LinkView }
  | { kind: 'gone' }
  | { kind: 'unavailable' };

const BOOKING_PREFIX = 'booking';

export function LinkLoader({ token }: { token: string }) {
  const router = useRouter();
  const [state, setState] = useState<State>({ kind: 'loading' });

  useEffect(() => {
    let current = true;
    void readLinkView(token).then((result) => {
      if (!current) return;
      if (result.kind === 'open' && result.view.purpose.startsWith(BOOKING_PREFIX)) {
        router.replace(`/l/${token}/booking`);
        return;
      }
      if (result.kind === 'open' && result.view.purpose !== 'capacity-reply') {
        setState({ kind: 'unavailable' });
        return;
      }
      setState(result.kind === 'open' ? { kind: 'open', view: result.view } : { kind: result.kind });
    });
    return () => {
      current = false;
    };
  }, [token, router]);

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
    case 'gone':
      return <LinkExpired token={token} />;
    case 'unavailable':
      return <LinkUnavailable />;
  }
}
