'use client';

import { useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';
import { bffRequest } from '@/lib/reporter/browser';
import { parseInvitation } from '@/lib/reporter/model';
import styles from './Setup.module.css';

// The invitation link's landing (W33): look the token up through the BFF, then go to the set-up
// flow with the token in the address. An expired or used invitation is said plainly; a failed
// check is not called expired, because nobody has checked it.

type State = 'checking' | 'expired' | 'failed';

export function InvitationLoader({ token }: { token: string }) {
  const router = useRouter();
  const [state, setState] = useState<State>('checking');

  useEffect(() => {
    let live = true;
    void bffRequest(`/api/bff/invitations/${encodeURIComponent(token)}`).then((reply) => {
      if (!live) return;
      // 410 is the back end's one answer for an invitation it will not use; a failed check is not that.
      if (reply.status === 410) return setState('expired');
      const invitation = reply.status === 200 ? parseInvitation(reply.body) : null;
      if (invitation === null) return setState('failed');
      if (invitation.state !== 'valid') return setState('expired');
      router.replace(`/setup?invite=${encodeURIComponent(token)}`);
    });
    return () => {
      live = false;
    };
  }, [token, router]);

  if (state === 'checking') {
    return (
      <main className={styles.page}>
        <p role="status">Checking your invitation</p>
      </main>
    );
  }
  return (
    <main className={styles.page}>
      <h1 className={styles.title}>{state === 'expired' ? 'This invitation has expired' : 'We could not check this invitation'}</h1>
      <p>
        {state === 'expired'
          ? 'This invitation has expired. Ask the shift lead to send a new one.'
          : 'We could not check this invitation. Try again shortly.'}
      </p>
    </main>
  );
}
