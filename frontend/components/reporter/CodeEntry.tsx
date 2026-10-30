'use client';

import { useEffect, useState } from 'react';
import { Banner } from '@/components/ui/Banner';
import { Button } from '@/components/ui/Button';
import { CodeInput } from './CodeInput';
import styles from './Reporter.module.css';

// The text code, for set-up, the 30-day check and a locked PIN (W33, W37, W55): six boxes, ten
// minutes to use it, five wrong tries, and a new code no sooner than a minute after the last one.
// The caller says how to send and how to check; this component only counts and shows.

export const RESEND_SECONDS = 60;
const LENGTH = 6;

export type CheckResult = { ok: true } | { ok: false; triesLeft: number | null };

type Props = {
  sendCode: () => Promise<boolean>;
  checkCode: (code: string) => Promise<CheckResult>;
  onVerified: () => void;
  caption?: string;
};

export function CodeEntry({ sendCode, checkCode, onVerified, caption }: Props) {
  const [code, setCode] = useState('');
  const [left, setLeft] = useState(RESEND_SECONDS);
  const [triesLeft, setTriesLeft] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  // One interval for the whole entry: the count reaches zero once per minute.
  useEffect(() => {
    const timer = setInterval(() => setLeft((s) => Math.max(0, s - 1)), 1000);
    return () => clearInterval(timer);
  }, []);

  const exhausted = triesLeft === 0;

  const check = async () => {
    setBusy(true);
    setNotice(null);
    const result = await checkCode(code);
    setBusy(false);
    if (result.ok) return onVerified();
    if (result.triesLeft === null) return setNotice('We could not check that code. Try again shortly.');
    setTriesLeft(result.triesLeft);
    setNotice(
      result.triesLeft === 0
        ? 'Too many tries. Send a new code.'
        : `That code is not right. You have ${result.triesLeft} ${result.triesLeft === 1 ? 'try' : 'tries'} left.`,
    );
    return undefined;
  };

  const resend = async () => {
    if (await sendCode()) {
      setLeft(RESEND_SECONDS);
      setTriesLeft(null);
      setCode('');
      setNotice(null);
    }
  };

  return (
    <div className={styles.page}>
      {caption !== undefined ? <p className={styles.eyebrow}>{caption}</p> : null}
      <CodeInput value={code} onChange={setCode} disabled={exhausted} dataEl="CODE-INPUT" />
      <p>The code works for 10 minutes. After 5 wrong tries you must ask for a new code.</p>
      {notice !== null ? <Banner tone="warning" title={notice} /> : null}
      <Button
        variant="primary"
        busy={busy}
        disabled={exhausted || code.length !== LENGTH}
        dataEl="CODE-CHECK-BTN"
        onClick={() => void check()}
      >
        Check code
      </Button>
      {left > 0 ? (
        <p>{`Send a new code in 0:${String(left).padStart(2, '0')}`}</p>
      ) : (
        <Button variant="neutral" dataEl="CODE-RESEND-BTN" onClick={() => void resend()}>
          Send a new code
        </Button>
      )}
    </div>
  );
}
