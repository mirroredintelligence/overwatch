'use client';

import { useEffect, useId, useState } from 'react';
import { CodeInput } from '@/components/reporter/CodeInput';
import { LinkExpired } from '@/components/reporter/LinkExpired';
import { LinkUnavailable } from '@/components/reporter/LinkUnavailable';
import { MOBILE_ERROR, MobileNumberField } from '@/components/reporter/MobileNumberField';
import { LinkFrame } from '@/components/reporter/parts/LinkFrame';
import { Button } from '@/components/ui/Button';
import { Loading, Skeleton } from '@/components/ui/Skeleton';
import { type CheckinStep, confirmCheckin, readCheckin, sendCheckinCode } from '@/lib/checkin/browser';
import { isUkMobile } from '@/lib/forms/ukMobile';
import styles from './CheckInPage.module.css';

// The page a service's printed QR code opens (DEC-1346). A duty manager gives the mobile number they were registered
// with, is texted a six-digit code, and then starts or finishes their shift. The page never says whether a number is on
// the roster: it says a code was sent, and a wrong or missing one is "that code did not work". It reads the code once
// (which sets its CSRF cookie); only a press writes.

type Phase =
  | { kind: 'loading' }
  | { kind: 'gone' }
  | { kind: 'unavailable' }
  | { kind: 'number'; service: string; csrf: string }
  | { kind: 'code'; service: string; csrf: string }
  | { kind: 'done'; message: string };

const HOURS = [4, 6, 8, 10, 12, 14] as const;
const DEFAULT_HOURS = 8;

const ERRORS: Partial<Record<CheckinStep['kind'], string>> = {
  'rate-limited': 'Too many tries. Wait a few minutes and try again.',
  'code-wrong': 'That code did not work. Check it, or ask for a new one.',
  invalid: 'Check the details and try again.',
  failed: 'That did not go through. Try again.',
};

export function CheckInPage({ token }: { token: string }) {
  const [phase, setPhase] = useState<Phase>({ kind: 'loading' });
  const [mobile, setMobile] = useState('');
  const [code, setCode] = useState('');
  const [hours, setHours] = useState<number>(DEFAULT_HOURS);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const hoursId = useId();

  useEffect(() => {
    let current = true;
    void readCheckin(token).then((result) => {
      if (!current) return;
      if (result.kind === 'ready') setPhase({ kind: 'number', service: result.service, csrf: result.csrfToken });
      else setPhase({ kind: result.kind });
    });
    return () => {
      current = false;
    };
  }, [token]);

  if (phase.kind === 'gone') return <LinkExpired token={token} csrfToken={null} />;
  if (phase.kind === 'unavailable') return <LinkUnavailable />;
  if (phase.kind === 'loading') {
    return (
      <LinkFrame>
        <main className={styles.stack}>
          <Loading label="Opening the check-in.">
            <div className={styles.card}>
              <Skeleton shape="title" width="62%" />
              <Skeleton shape="block" />
            </div>
          </Loading>
        </main>
      </LinkFrame>
    );
  }
  if (phase.kind === 'done') {
    return (
      <LinkFrame>
        <main className={styles.stack}>
          <section className={styles.card} data-el="CHECKIN-DONE">
            <h1 className={styles.heading}>{phase.message}</h1>
            <p className={styles.body}>You can close this page.</p>
          </section>
        </main>
      </LinkFrame>
    );
  }

  const { service, csrf } = phase;

  async function ask() {
    if (!isUkMobile(mobile)) {
      setError(MOBILE_ERROR);
      return;
    }
    setBusy(true);
    setError(null);
    const result = await sendCheckinCode(token, csrf, mobile);
    setBusy(false);
    if (result.kind === 'sent') {
      setPhase({ kind: 'code', service, csrf });
      return;
    }
    if (result.kind === 'gone') {
      setPhase({ kind: 'gone' });
      return;
    }
    setError(ERRORS[result.kind] ?? ERRORS.failed ?? null);
  }

  async function confirm(action: 'on' | 'off') {
    setBusy(true);
    setError(null);
    const result = await confirmCheckin(token, csrf, action === 'on' ? { mobile, code, action, hours } : { mobile, code, action });
    setBusy(false);
    if (result.kind === 'on-shift') {
      const until = result.until === null ? '' : ` until ${result.until}`;
      setPhase({ kind: 'done', message: `You are on shift for ${result.service}${until}.` });
      return;
    }
    if (result.kind === 'off-shift') {
      setPhase({ kind: 'done', message: `You are off shift for ${service}.` });
      return;
    }
    if (result.kind === 'gone') {
      setPhase({ kind: 'gone' });
      return;
    }
    setCode('');
    setError(ERRORS[result.kind] ?? ERRORS.failed ?? null);
  }

  return (
    <LinkFrame>
      <main className={styles.stack}>
        <section className={styles.card} data-el="CHECKIN">
          <p className={styles.eyebrow}>Duty manager check-in</p>
          <h1 className={styles.heading}>{service}</h1>
          {phase.kind === 'number' ? (
            <>
              <p className={styles.body}>Enter the mobile number you were registered with. We will text you a code.</p>
              <MobileNumberField label="Your mobile number" value={mobile} onChange={setMobile} error={error === MOBILE_ERROR ? error : null} required />
              <Button variant="primary" busy={busy} onClick={() => void ask()} dataEl="CHECKIN-SEND-BTN">
                Text me a code
              </Button>
            </>
          ) : (
            <>
              <p className={styles.body}>If that number is registered for this service, a code is on its way. Enter it here.</p>
              <CodeInput value={code} onChange={setCode} disabled={busy} dataEl="CHECKIN-CODE" />
              <div className={styles.field}>
                <label htmlFor={hoursId} className={styles.label}>
                  How long is your shift?
                </label>
                <select id={hoursId} className={styles.select} value={hours} onChange={(event) => setHours(Number(event.target.value))}>
                  {HOURS.map((option) => (
                    <option key={option} value={option}>{`${option} hours`}</option>
                  ))}
                </select>
              </div>
              <div className={styles.actions}>
                <Button variant="primary" busy={busy} disabled={code.length !== 6} onClick={() => void confirm('on')} dataEl="CHECKIN-ON-BTN">
                  Start my shift
                </Button>
                <Button variant="secondary" busy={busy} disabled={code.length !== 6} onClick={() => void confirm('off')} dataEl="CHECKIN-OFF-BTN">
                  Finish my shift
                </Button>
              </div>
              <Button variant="neutral" onClick={() => { setPhase({ kind: 'number', service, csrf }); setCode(''); setError(null); }}>
                Use a different number
              </Button>
            </>
          )}
          {error !== null && error !== MOBILE_ERROR ? (
            <p role="alert" className={styles.error}>
              {error}
            </p>
          ) : null}
        </section>
      </main>
    </LinkFrame>
  );
}
