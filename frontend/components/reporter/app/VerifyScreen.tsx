'use client';

import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { CodeEntry, type CheckResult } from '@/components/reporter/CodeEntry';
import { Banner } from '@/components/ui/Banner';
import { Button } from '@/components/ui/Button';
import { bffRequest } from '@/lib/reporter/browser';
import styles from './Recovery.module.css';

// The 30-day check (W37, B8): a text code to the number the back end holds for this phone's device, then
// back to the app. The same screen morphs to the six-digit entry after Send code. The board shows the
// number masked; the phone has no session to read it from here, so the words say "the number we have".

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

  if (started) {
    return (
      <main className={styles.page}>
        <CodeEntry
          sendCode={sendCode}
          checkCode={checkCode}
          onVerified={() => router.replace('/app')}
          intro={
            <>
              <h1 className={styles.title}>Enter your code</h1>
              <p className={styles.lead}>We sent a code to the number we have for you.</p>
            </>
          }
        >
          <p className={styles.note}>After 5 wrong tries you must ask for a new code.</p>
        </CodeEntry>
      </main>
    );
  }

  return (
    <main className={styles.page}>
      <div className={styles.card}>
        <h1 className={styles.title}>Check it is you</h1>
        <p className={styles.lead}>It has been 30 days. We will text a code to the number we have for you.</p>
        <p className={styles.note}>You do not need to do this again for another 30 days.</p>
      </div>
      {notice !== null ? <Banner tone="warning" title={notice} /> : null}
      <div className={styles.actions}>
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
      </div>
    </main>
  );
}
