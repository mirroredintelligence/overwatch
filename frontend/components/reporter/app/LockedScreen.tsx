'use client';

import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { CodeEntry } from '@/components/reporter/CodeEntry';
import { PinSetup } from '@/components/reporter/setup/PinSetup';
import { Button } from '@/components/ui/Button';
import { bffRequest } from '@/lib/reporter/browser';
import styles from '@/components/reporter/Reporter.module.css';

// The locked PIN (W37): a text code, then a new PIN entered twice. "Forgot your PIN?" (the link
// from the PIN screen) has the same way out, without the five-tries line.

type Stage = 'start' | 'code' | 'pin';

export function LockedScreen({ reason }: { reason: string | null }) {
  const router = useRouter();
  const [stage, setStage] = useState<Stage>('start');
  const [notice, setNotice] = useState<string | null>(null);
  const forgot = reason === 'forgot';

  const sendCode = async () => (await bffRequest('/api/bff/identity/code', { method: 'POST', body: { purpose: 'pin-reset' } })).status === 202;

  const checkCode = async (code: string) => {
    const reply = await bffRequest('/api/bff/identity/code/verify', { method: 'POST', body: { purpose: 'pin-reset', code } });
    const body = reply.body as { ok?: boolean; triesLeft?: number } | undefined;
    if (reply.status === 200 && body?.ok === true) return { ok: true as const };
    return { ok: false as const, triesLeft: typeof body?.triesLeft === 'number' ? body.triesLeft : null };
  };

  const textMe = async () => {
    setNotice(null);
    if (await sendCode()) return setStage('code');
    return setNotice('We could not send a code. Try again shortly.');
  };

  const chooseText = async () => {
    const reply = await bffRequest('/api/bff/reporter/channel', { method: 'POST', body: { channel: 'text' } });
    if (reply.status === 200 || reply.status === 204) router.push('/app/settings');
    else setNotice('We could not change how we contact you. Try again.');
  };

  if (stage === 'code') {
    return <CodeEntry caption="Enter the code" sendCode={sendCode} checkCode={checkCode} onVerified={() => setStage('pin')} />;
  }
  if (stage === 'pin') return <PinSetup doneHref="/app" />;

  return (
    <main className={styles.page}>
      <h1 className={styles.title}>{forgot ? 'Forgot your PIN?' : 'Your PIN is locked'}</h1>
      {forgot ? null : <p>That was 5 wrong tries. Get a code by text to set a new PIN.</p>}
      <p>Nothing was sent or changed.</p>
      {notice !== null ? <p role="alert">{notice}</p> : null}
      <Button variant="primary" dataEl="REP-LOCKED-CODE-BTN" onClick={() => void textMe()}>
        Text me a code
      </Button>
      <Button variant="neutral" dataEl="REP-LOCKED-CHANNEL-BTN" onClick={() => void chooseText()}>
        Use text or email instead
      </Button>
    </main>
  );
}
