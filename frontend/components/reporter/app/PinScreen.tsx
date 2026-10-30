'use client';

import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { PinPad } from '@/components/reporter/PinPad';
import { Banner } from '@/components/ui/Banner';
import { bffRequest } from '@/lib/reporter/browser';
import styles from '@/components/reporter/Reporter.module.css';

// Sign in with the PIN (W35). Wrong tries are counted by the back end; this screen says how many
// are left and moves on when the back end says the PIN is locked or a text code is needed.

type Answer = { ok?: boolean; triesLeft?: number; locked?: boolean; reverify?: boolean };

export function PinScreen() {
  const router = useRouter();
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (pin: string) => {
    setBusy(true);
    setNotice(null);
    const reply = await bffRequest('/api/bff/identity/pin/verify', { method: 'POST', body: { pin } });
    setBusy(false);
    const answer = (reply.body ?? {}) as Answer;
    if (reply.status === 200 && answer.ok === true) return router.replace('/app');
    if (answer.locked === true) return router.push('/app/locked');
    if (answer.reverify === true) return router.push('/app/verify');
    if (typeof answer.triesLeft === 'number') {
      const left = answer.triesLeft;
      return setNotice(`That PIN is not right. ${left} ${left === 1 ? 'try' : 'tries'} left.`);
    }
    return setNotice('Sign-in is not available right now. Try again shortly.');
  };

  return (
    <main className={styles.page}>
      <h1 className={styles.title}>Enter your PIN</h1>
      {notice !== null ? <Banner tone="warning" title={notice} /> : null}
      <PinPad label="Enter your PIN" onComplete={(pin) => void submit(pin)} dataEl="REP-APP" />
      {busy ? <p role="status">Checking your PIN</p> : null}
      <p className={styles.footer}>
        <a href="/app/locked?reason=forgot">Forgot your PIN?</a>
      </p>
      <p className={styles.footer}>
        <a href="/app/lost-phone">Lost your phone?</a>
      </p>
    </main>
  );
}
