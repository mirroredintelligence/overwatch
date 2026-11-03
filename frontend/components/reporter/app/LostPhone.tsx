'use client';

import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { CodeEntry, type CheckResult } from '@/components/reporter/CodeEntry';
import { MOBILE_ERROR, MobileNumberField } from '@/components/reporter/MobileNumberField';
import { Button } from '@/components/ui/Button';
import { isUkMobile } from '@/lib/forms/ukMobile';
import { bffRequest } from '@/lib/reporter/browser';
import { StatusTag } from '@/components/ui/StatusTag';
import styles from './LostPhone.module.css';

// Lost your phone? (W55). No session is needed: the new phone is proved by a text code to the number
// we hold, and the lead's call-back then confirms the phone. Old phones are signed out only once the
// code is checked. Nothing here says whether a number is known to us.

const MESSAGES: Record<string, string> = {
  wrong: 'That code is not right.',
  expired: 'That code has expired. Ask for a new code.',
  throttled: 'Too many wrong tries. Ask for a new code.',
};

type Stage = 'number' | 'code' | 'waiting';

export function LostPhone() {
  const router = useRouter();
  const [stage, setStage] = useState<Stage>('number');
  const [phone, setPhone] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [codeNotice, setCodeNotice] = useState<string | null>(null);
  const [spoaPhone, setSpoaPhone] = useState<string | null>(null);

  const sendCode = async () => (await bffRequest('/api/bff/identity/new-phone', { method: 'POST', body: { phone } })).status === 202;

  const send = async () => {
    if (!isUkMobile(phone)) return setError(MOBILE_ERROR);
    setError(null);
    setBusy(true);
    const sent = await sendCode();
    setBusy(false);
    if (sent) return setStage('code');
    return setError('We could not send a code. Try again shortly.');
  };

  const checkCode = async (code: string): Promise<CheckResult> => {
    const reply = await bffRequest('/api/bff/identity/new-phone/verify', { method: 'POST', body: { phone, code } });
    if (reply.status === 200) {
      // The tenant's coordination number, or none (never a default): shown on the wait.
      const number = (reply.body as { spoaPhone?: unknown } | undefined)?.spoaPhone;
      setSpoaPhone(typeof number === 'string' && number !== '' ? number : null);
      return { ok: true };
    }
    const coded = (reply.body as { code?: string } | undefined)?.code;
    setCodeNotice(MESSAGES[coded ?? ''] ?? 'We could not check that code. Try again shortly.');
    return { ok: false, triesLeft: null };
  };

  if (stage === 'code') {
    return (
      <main className={styles.page}>
        <h1 className={styles.title}>Enter the code</h1>
        {codeNotice !== null ? <p role="alert">{codeNotice}</p> : null}
        <CodeEntry sendCode={sendCode} checkCode={checkCode} onVerified={() => setStage('waiting')} />
      </main>
    );
  }

  if (stage === 'waiting') {
    return (
      <main className={styles.page}>
        <div className={styles.card}>
          <StatusTag variant="paused">Not live yet</StatusTag>
          <h1 className={styles.title}>Waiting for a call-back</h1>
          <p className={styles.lead}>The shift lead will phone your service on the number on the register.</p>
          <p className={styles.soft}>Until then, prompts go to your cover number or the coordination team.</p>
          {spoaPhone === null ? <p className={styles.soft}>Phone the coordination team.</p> : null}
        </div>
        {spoaPhone === null ? null : (
          <div className={styles.wide}>
            <Button variant="primary" dataEl="REP-LOST-PHONE-LINK" href={`tel:${spoaPhone.replace(/\s+/g, '')}`}>
              {`Phone the coordination team on ${spoaPhone}`}
            </Button>
          </div>
        )}
        <button type="button" className={styles.plain} data-variant="text" data-el="REP-LOST-CALLBACK-BTN" onClick={() => router.push('/app/pin')}>
          Back to sign in
        </button>
      </main>
    );
  }

  return (
    <main className={styles.page}>
      <div className={styles.card}>
        <h1 className={styles.title}>Lost your phone?</h1>
        <p className={styles.lead}>Use your new phone. We text a code to the number we have for you.</p>
        <div className={styles.fieldWrap}>
          <MobileNumberField label="Mobile number" value={phone} onChange={setPhone} error={error} required dataEl="REP-LOST-PHONE" />
        </div>
      </div>
      <p className={styles.note} data-el="REP-LOST-NOTE">
        Your old phone is signed out as soon as you verify. The shift lead phones your service before your new phone goes live.
      </p>
      <div className={styles.wide}>
        <Button variant="primary" busy={busy} dataEl="REP-LOST-SEND-BTN" onClick={() => void send()}>
          Send code
        </Button>
      </div>
      <button type="button" className={styles.plain} data-variant="text" data-el="REP-LOST-BACK-BTN" onClick={() => router.push('/app/pin')}>
        Back
      </button>
    </main>
  );
}
