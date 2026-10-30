'use client';

import { useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';
import { Banner } from '@/components/ui/Banner';
import { Button } from '@/components/ui/Button';
import { bffRequest } from '@/lib/reporter/browser';
import styles from '@/components/reporter/Reporter.module.css';

// Sign out of every phone (W55): for a lost, shared or stolen phone. The count of other phones comes
// from settings. After success this phone's session is cleared and the PIN screen is shown.

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
    if (reply.status === 200) {
      await bffRequest('/api/bff/session', { method: 'DELETE' });
      router.push('/app/pin');
      return;
    }
    setBusy(false);
    setNotice('We could not sign out your phones. Try again.');
  };

  const count = others ?? 0;
  return (
    <main className={styles.page}>
      <h1 className={styles.title}>Sign out of every phone?</h1>
      <p>Use this if a phone is lost, shared or stolen. You will sign in again with a text code and your PIN.</p>
      {others !== null ? <p>{`This phone and ${count} ${count === 1 ? 'other' : 'others'} will be signed out.`}</p> : null}
      {notice !== null ? <Banner tone="warning" title={notice} /> : null}
      <Button variant="primary" busy={busy} dataEl="REP-SIGNOUTALL-CONFIRM-BTN" onClick={() => void confirm()}>
        Sign out of all phones
      </Button>
      <Button variant="neutral" dataEl="REP-SIGNOUTALL-CANCEL-BTN" onClick={() => router.push('/app/settings')}>
        Cancel
      </Button>
    </main>
  );
}
