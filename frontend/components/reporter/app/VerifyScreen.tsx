'use client';

import { useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';
import { CodeEntry, type CheckResult } from '@/components/reporter/CodeEntry';
import { Button } from '@/components/ui/Button';
import { bffRequest } from '@/lib/reporter/browser';
import styles from '@/components/reporter/Reporter.module.css';

// The 30-day check (W37): a text code to the reporter's own number, then back to the app. The
// number is shown masked, from the settings the BFF reads.

export function VerifyScreen() {
  const router = useRouter();
  const [masked, setMasked] = useState<string | null>(null);
  const [started, setStarted] = useState(false);

  useEffect(() => {
    let live = true;
    void bffRequest('/api/bff/reporter/settings').then((reply) => {
      const body = reply.body as { maskedPhone?: unknown } | undefined;
      if (live && reply.status === 200 && typeof body?.maskedPhone === 'string') setMasked(body.maskedPhone);
    });
    return () => {
      live = false;
    };
  }, []);

  const sendCode = async () => (await bffRequest('/api/bff/identity/code', { method: 'POST', body: { purpose: 'reverify' } })).status === 202;

  const checkCode = async (code: string): Promise<CheckResult> => {
    const reply = await bffRequest('/api/bff/identity/code/verify', { method: 'POST', body: { purpose: 'reverify', code } });
    const body = reply.body as { ok?: boolean; triesLeft?: number } | undefined;
    if (reply.status === 200 && body?.ok === true) return { ok: true };
    return { ok: false, triesLeft: typeof body?.triesLeft === 'number' ? body.triesLeft : null };
  };

  if (started) return <CodeEntry caption="Check it is you" sendCode={sendCode} checkCode={checkCode} onVerified={() => router.replace('/app')} />;

  return (
    <main className={styles.page}>
      <h1 className={styles.title}>Check it is you</h1>
      <p>{masked === null ? 'It has been 30 days. We will text a code to your number.' : `It has been 30 days. We will text a code to ${masked}.`}</p>
      <p>You do not need to do this again for another 30 days.</p>
      <Button
        variant="primary"
        dataEl="REP-VERIFY-SEND-BTN"
        onClick={async () => {
          if (await sendCode()) setStarted(true);
        }}
      >
        Send code
      </Button>
    </main>
  );
}
