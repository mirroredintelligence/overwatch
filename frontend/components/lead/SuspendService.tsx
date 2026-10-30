'use client';

import { useEffect, useId, useState, type FormEvent } from 'react';
import { PhonedDialog } from '@/components/advisor/PhonedDialog';
import { Button } from '@/components/ui/Button';
import { CANNOT_DO, leadPost, leadRead } from '@/lib/lead/browser';
import { clockTime } from '@/lib/lead/format';
import styles from './Lead.module.css';

// Suspend and resume one service (W42). A suspension is the shift lead's act: the page asks why, says what
// happens at once, and then shows the suspended view from the answer. The back end does not give the
// suspension state on a read, so a fresh visit shows the suspend form (DEC-657). Resuming needs two
// confirmations, and the call-back to the register number is the lead's own (the service is phoned).

type Phase = 'suspend' | 'suspended' | 'resume' | 'resumed';

const REASONS: [string, string][] = [
  ['suspected-false-reports', 'Suspected false reports'],
  ['closed-unexpectedly', 'Closed unexpectedly'],
  ['contact-unreachable', 'Contact cannot be reached'],
  ['other', 'Other'],
];

const HAPPENS: string[] = [
  'The board shows Not updated, phone to confirm.',
  'The service leaves the options.',
  'Prompts stop.',
  'Open requests expire.',
];

type Suspension = { since: string; expiredRequests: number; notified: boolean };

function expiredWords(count: number): string {
  if (count === 0) return 'No open requests expired.';
  return `${count} open ${count === 1 ? 'request' : 'requests'} expired.`;
}

export function SuspendService({ serviceId }: { serviceId: string }) {
  const [name, setName] = useState<string | null>(null);
  const [phase, setPhase] = useState<Phase>('suspend');
  const [reason, setReason] = useState<string | null>(null);
  const [reasonError, setReasonError] = useState(false);
  const [suspension, setSuspension] = useState<Suspension | null>(null);
  const [phoned, setPhoned] = useState(false);
  const [resolved, setResolved] = useState(false);
  const [nextDue, setNextDue] = useState<string | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [phonedDialog, setPhonedDialog] = useState(false);
  const reasonGroupId = useId();

  useEffect(() => {
    let cancelled = false;
    void leadRead(`/api/bff/lead/services/${encodeURIComponent(serviceId)}`).then((result) => {
      const body = result.ok ? (result.body as { name?: unknown }) : undefined;
      if (!cancelled && typeof body?.name === 'string') setName(body.name);
    });
    return () => {
      cancelled = true;
    };
  }, [serviceId]);

  const label = name ?? 'this service';

  async function suspend(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    setFailure(null);
    if (reason === null) {
      setReasonError(true);
      return;
    }
    setReasonError(false);
    setBusy(true);
    const result = await leadPost(`/api/bff/lead/services/${encodeURIComponent(serviceId)}/suspend`, { reason });
    setBusy(false);
    if (!result.ok) {
      setFailure(result.status === 403 ? CANNOT_DO : 'The service could not be suspended. Try again.');
      return;
    }
    setSuspension(result.body as Suspension);
    setPhase('suspended');
  }

  async function resume() {
    if (!phoned || !resolved || busy) return;
    setFailure(null);
    setBusy(true);
    const result = await leadPost(`/api/bff/lead/services/${encodeURIComponent(serviceId)}/resume`, {
      phonedRegisterNumber: true,
      reasonResolved: true,
    });
    setBusy(false);
    if (!result.ok) {
      setFailure(result.status === 403 ? CANNOT_DO : 'The service could not be resumed. Try again.');
      return;
    }
    const due = (result.body as { nextDueAt?: unknown } | undefined)?.nextDueAt;
    setNextDue(typeof due === 'string' ? due : null);
    setPhase('resumed');
  }

  if (phase === 'suspend') {
    return (
      <main className={styles.page}>
        <h1 className={styles.title}>{`Suspend ${label}`}</h1>

        <section className={styles.section} aria-labelledby="suspend-happens-heading">
          <h2 id="suspend-happens-heading" className={styles.sectionHeading}>
            What happens at once
          </h2>
          <ul aria-label="What happens at once" className={styles.ladder}>
            {HAPPENS.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </section>

        <form onSubmit={(event) => void suspend(event)} noValidate className={styles.stack}>
          <fieldset className={styles.choices} aria-describedby={reasonError ? `${reasonGroupId}-error` : undefined}>
            <legend className={styles.fieldLabel}>Why?</legend>
            {reasonError ? (
              <p id={`${reasonGroupId}-error`} role="alert" className={styles.fieldError}>
                Choose why
              </p>
            ) : null}
            {REASONS.map(([value, text]) => (
              <label key={value} className={styles.radio}>
                <input
                  type="radio"
                  name="suspend-reason"
                  value={value}
                  checked={reason === value}
                  onChange={() => setReason(value)}
                  data-el={`LEAD-SUSPEND-REASON-${value.toUpperCase()}`}
                />
                {text}
              </label>
            ))}
          </fieldset>
          {failure ? (
            <p role="alert" className={styles.fieldError}>
              {failure}
            </p>
          ) : null}
          <div className={styles.actions}>
            <Button variant="primary" type="submit" busy={busy} dataEl="LEAD-SUSPEND-BTN">
              Suspend service
            </Button>
            <Button variant="neutral" href="/lead">
              Cancel
            </Button>
          </div>
        </form>
        <p role="status" className={styles.line} />
      </main>
    );
  }

  if (phase === 'suspended' && suspension !== null) {
    return (
      <main className={styles.page}>
        <h1 className={styles.title}>{`${label} is suspended`}</h1>
        <p className={styles.line}>
          <span>{`Since ${clockTime(suspension.since)}.`}</span> <span>{expiredWords(suspension.expiredRequests)}</span>
        </p>
        <p className={styles.line}>
          {suspension.notified
            ? 'The service was told by text. Resuming needs a call-back.'
            : 'The service could not be told by text. Resuming needs a call-back.'}
        </p>
        <section className={styles.section} aria-labelledby="suspend-phone-heading">
          <h2 id="suspend-phone-heading" className={styles.sectionHeading}>
            Phone the service
          </h2>
          <p className={styles.muted}>The register number is not on this screen yet.</p>
          <div className={styles.actions}>
            <Button variant="neutral" onClick={() => setPhonedDialog(true)} dataEl="LEAD-SUSPEND-PHONED-BTN">
              Enter what they told me by phone
            </Button>
          </div>
        </section>
        <div className={styles.actions}>
          <Button variant="primary" onClick={() => setPhase('resume')} dataEl="LEAD-RESUME-BTN">
            Resume service
          </Button>
        </div>
        <PhonedDialog open={phonedDialog} serviceName={label} onClose={() => setPhonedDialog(false)} />
      </main>
    );
  }

  if (phase === 'resume') {
    const ready = phoned && resolved;
    return (
      <main className={styles.page}>
        <h1 className={styles.title}>{`Resume ${label}`}</h1>
        <section className={styles.section} aria-labelledby="resume-before-heading">
          <h2 id="resume-before-heading" className={styles.sectionHeading}>
            Before you resume
          </h2>
          <label className={styles.checkbox}>
            <input type="checkbox" checked={phoned} onChange={(e) => setPhoned(e.target.checked)} />
            I phoned the service on the register number
          </label>
          <label className={styles.checkbox}>
            <input type="checkbox" checked={resolved} onChange={(e) => setResolved(e.target.checked)} />
            The reason is resolved
          </label>
          <p className={styles.muted}>Both are needed</p>
          <p className={styles.muted}>Resuming is logged with who and when.</p>
        </section>
        {failure ? (
          <p role="alert" className={styles.fieldError}>
            {failure}
          </p>
        ) : null}
        <div className={styles.actions}>
          <Button variant="primary" disabled={!ready} busy={busy} onClick={() => void resume()} dataEl="LEAD-RESUME-CONFIRM-BTN">
            Resume service
          </Button>
        </div>
      </main>
    );
  }

  return (
    <main className={styles.page}>
      <h1 className={styles.title}>{label}</h1>
      <p role="status" className={styles.line}>
        {`Resumed.${nextDue !== null ? ` Next report due ${clockTime(nextDue)}.` : ''}`}
      </p>
    </main>
  );
}
