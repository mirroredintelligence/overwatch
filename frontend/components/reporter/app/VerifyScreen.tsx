'use client';

import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { CodeEntry, type CheckResult } from '@/components/reporter/CodeEntry';
import { Banner } from '@/components/ui/Banner';
import { Button } from '@/components/ui/Button';
import { bffRequest } from '@/lib/reporter/browser';
import styles from '@/components/reporter/Reporter.module.css';

// The 30-day check (W37): a text code to the reporter's own number, then back to the app. The
// number is shown masked, from the settings the BFF reads.

export function VerifyScreen() {
  const router = useRouter();
  const [started, setStarted] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  const sendCode = async () => (await bffRequest('/api/bff/identity/device-code', { method: 'POST', body: { purpose: 'reverify' } })).status === 202;

  const checkCode = async (code: string): Promise<CheckResult> => {
    const reply = await bffRequest('/api/bff/identity/device-code/verify', { method: 'POST', body: { purpose: 'reverify', code } });
    const body = reply.body as { ok?: boolean; triesLeft?: number } | undefined;
    if (reply.status === 200 && body?.ok === true) return { ok: true };
    return { ok: false, triesLeft: typeof body?.triesLeft === 'number' ? body.triesLeft : null };
  };

  if (started) return <CodeEntry caption="Check it is you" sendCode={sendCode} checkCode={checkCode} onVerified={() => router.replace('/app')} />;

  return (
    <main className={styles.page}>
      <h1 className={styles.title}>Check it is you</h1>
      <p>It has been 30 days. We will text a code to the number we have for you.</p>
      <p>You do not need to do this again for another 30 days.</p>
      {notice !== null ? <Banner tone="warning" title={notice} /> : null}
      <Button
        variant="primary"
        dataEl="REP-VERIFY-SEND-BTN"
        onClick={async () => {
          setNotice(null);
          if (await sendCode()) setStarted(true);
          else setNotice('We could not send a code. Try again shortly.');
        }}
      >
        Send code
      </Button>
    </main>
  );
}
