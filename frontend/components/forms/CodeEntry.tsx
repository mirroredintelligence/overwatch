'use client';

import { useEffect, useId, useState } from 'react';
import { Button } from '@/components/ui/Button';
import { TextField } from './TextField';
import styles from './CodeEntry.module.css';

// The text code screen (W23, artboard OnboardReporter1 panel 4). It shows the number as its last three
// digits only: the page is given no more than that (DEC-900). The resend is offered after one minute: until then
// a countdown runs, so a second code cannot be asked for by impatience.

export const RESEND_SECONDS = 60;
const CODE = /^\d{6}$/;

export type CodeEntryProps = {
  /** The last three digits of the number the code went to (DEC-900). The page never holds more. */
  ending: string;
  error?: string | null;
  busy?: boolean;
  onCheck: (code: string) => void;
  onResend: () => void;
};

function countdownLabel(seconds: number): string {
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;
}

export function CodeEntry({ ending, error = null, busy = false, onCheck, onResend }: CodeEntryProps) {
  const id = useId();
  const [code, setCode] = useState('');
  const [remaining, setRemaining] = useState(RESEND_SECONDS);
  const [cycle, setCycle] = useState(0);
  const done = remaining === 0;

  // One tick a second until the count reaches zero. A new cycle (after a resend) starts it again.
  useEffect(() => {
    if (done) return undefined;
    const timer = setInterval(() => setRemaining((r) => (r > 0 ? r - 1 : 0)), 1000);
    return () => clearInterval(timer);
  }, [cycle, done]);

  return (
    <section className={styles.panel} aria-labelledby={`${id}-heading`}>
      <h2 id={`${id}-heading`} className={styles.heading}>
        Enter your code
      </h2>
      <p className={styles.text}>We sent a code to 07xxx xxx{ending}.</p>
      <TextField
        id={`${id}-code`}
        label="6-digit code"
        value={code}
        onChange={setCode}
        requirement="none"
        type="text"
        inputMode="numeric"
        autoComplete="one-time-code"
        maxLength={6}
        error={error}
        dataEl="REG-CODE-FIELD"
      />
      <Button
        variant="primary"
        busy={busy}
        disabled={!CODE.test(code)}
        dataEl="REG-CODE-CHECK-BTN"
        onClick={() => onCheck(code)}
      >
        Check code
      </Button>
      {done ? (
        <Button
          variant="secondary"
          dataEl="REG-CODE-RESEND-BTN"
          onClick={() => {
            setRemaining(RESEND_SECONDS);
            setCycle((c) => c + 1);
            onResend();
          }}
        >
          Send a new code
        </Button>
      ) : (
        <p className={styles.countdown}>Send a new code in {countdownLabel(remaining)}</p>
      )}
      <p className={styles.note}>The code works for 10 minutes. After 5 wrong tries you must ask for a new code.</p>
    </section>
  );
}
