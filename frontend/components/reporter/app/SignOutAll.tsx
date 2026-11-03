'use client';

import { useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';
import { Banner } from '@/components/ui/Banner';
import { Button } from '@/components/ui/Button';
import { bffRequest } from '@/lib/reporter/browser';
import styles from './SignOutAll.module.css';

// Sign out of every phone (W55, artboard B9): for a lost, shared or stolen phone. The count of other phones comes
// from settings. After success this phone's session is cleared and the PIN screen is shown. The confirm is the
// one primary action and it is dark, not red.

export function SignOutAll() {
  const router = useRouter();
  const [others, setOthers] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    void bffRequest('/api/bff/reporter/settings').then((reply) => {
      if (!live) return;
      if (reply.status === 401) return router.replace('/app/pin');
      const count = (reply.body as { otherDevices?: unknown } | undefined)?.otherDevices;
      setOthers(reply.status === 200 && typeof count === 'number' ? count : 0);
    });
    return () => {
      live = false;
    };
  }, [router]);

  const confirm = async () => {
    setBusy(true);
    const reply = await bffRequest('/api/bff/identity/sign-out-everywhere', { method: 'POST', body: {} });
    // The BFF ended this phone's session with the sign-out, so nothing more is asked of the session route.
    if (reply.status === 200 || reply.status === 401) {
      router.push('/app/pin');
      return;
    }
    setBusy(false);
    setNotice('We could not sign out your phones. Try again.');
  };

  const count = others ?? 0;
  return (
    <main className={styles.page}>
      <div className={styles.card}>
        <h1 className={styles.title}>Sign out of every phone?</h1>
        <p className={styles.why}>Use this if a phone is lost, shared or stolen. You will sign in again with a text code and your PIN.</p>
        {others !== null ? <p className={styles.count}>{`This phone and ${count} ${count === 1 ? 'other' : 'others'} will be signed out.`}</p> : null}
      </div>
      {notice !== null ? <Banner tone="warning" title={notice} /> : null}
      <button
        type="button"
        className={styles.dark}
        data-variant="dark"
        data-el="REP-SIGNOUTALL-CONFIRM-BTN"
        disabled={busy}
        aria-busy={busy ? 'true' : undefined}
        onClick={() => void confirm()}
      >
        Sign out of all phones
      </button>
      <div className={styles.wide}>
        <Button variant="secondary" dataEl="REP-SIGNOUTALL-CANCEL-BTN" onClick={() => router.push('/app/settings')}>
          Cancel
        </Button>
      </div>
    </main>
  );
}
