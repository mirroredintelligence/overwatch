'use client';

import { useEffect, useId, useRef, useState, type KeyboardEvent } from 'react';
import { Button } from '@/components/ui/Button';
import { OptionButton } from '@/components/ui/OptionButton';
import { ADVICE_LABELS, REASON_LABELS } from '@/lib/clinical/advice';
import { bffRequest } from '@/lib/bff/browser';
import styles from '@/components/exec/Exec.module.css';

// "Ask a clinical advisor" (W45, AdvisorActions and AdvisorDialogsPhone). A modal: focus moves to its
// heading when it opens and is kept inside it, Escape closes it, and focus goes back to the button that
// opened it. While a request waits it reads the request every five seconds and stops once advice arrives.
// The case summary is what the caller passed in; the only other read is the count of advisors available.

export type CaseSummary = {
  ageBand: string;
  district: string;
  needs: string[];
  within: string;
  news2: number;
  frailtyScale: number;
};

type Urgency = 'now' | 'within-15-min';
type Why = 'borderline-criteria' | 'unsure-of-urgency' | 'other';
type Phase = 'ask' | 'waiting' | 'taken' | 'advised' | 'returned';
type Answer = { state: 'waiting' | 'taken' | 'advised' | 'returned'; takenByRole?: string; takenAt?: string; advice?: string; reason?: string };

export const POLL_MS = 5_000;
export const NONE_AVAILABLE = 'No clinical advisor is available now. Use the escalation route under local protocol.';
const URGENCY_LABELS: Readonly<Record<Urgency, string>> = { now: 'Now', 'within-15-min': 'Within 15 min' };
const WHY_LABELS: Readonly<Record<Why, string>> = { 'borderline-criteria': 'Borderline criteria', 'unsure-of-urgency': 'Unsure of urgency', other: 'Other' };
const WHY_CHOICES: readonly Why[] = ['borderline-criteria', 'unsure-of-urgency', 'other'];
const ADVICE_CHOICE_LABEL = (advice: string) => (advice in ADVICE_LABELS ? ADVICE_LABELS[advice as keyof typeof ADVICE_LABELS] : advice);
// The reason reads inside a sentence, so its first letter is lower case ("Reason: within criteria on my judgement.").
const REASON_TEXT = (reason: string) => {
  const label = reason in REASON_LABELS ? REASON_LABELS[reason as keyof typeof REASON_LABELS] : reason;
  return label.charAt(0).toLowerCase() + label.slice(1);
};

function clock(instant: string): string {
  return new Intl.DateTimeFormat('en-GB', { timeZone: 'Europe/London', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).format(new Date(instant));
}

export function AskClinicalDialog({
  caseRef,
  summary,
  optionsShown,
  onClose,
}: {
  caseRef: string;
  summary: CaseSummary;
  optionsShown: number;
  onClose: () => void;
}) {
  const [urgency, setUrgency] = useState<Urgency>('now');
  const [why, setWhy] = useState<Why | null>(null);
  const [available, setAvailable] = useState<number | null>(null);
  const [phase, setPhase] = useState<Phase>('ask');
  const [requestId, setRequestId] = useState<string | null>(null);
  const [answer, setAnswer] = useState<Answer | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  const opener = useRef<HTMLElement | null>(null);
  const titleId = useId();

  // Focus: remember the opener, move focus to the heading, and give focus back when the dialog goes.
  useEffect(() => {
    opener.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    headingRef.current?.focus();
    const returnTo = opener.current;
    return () => returnTo?.focus();
  }, []);

  // How many advisors are available now: the one read this dialog makes before it is asked.
  useEffect(() => {
    let active = true;
    void bffRequest<{ available: number }>('/api/bff/clinical/summary').then((result) => {
      if (active && result.ok) setAvailable(result.data.available);
    });
    return () => {
      active = false;
    };
  }, []);

  // Poll the request while it waits or is taken; stop when advice (or a return) arrives.
  useEffect(() => {
    if (requestId === null || (phase !== 'waiting' && phase !== 'taken')) return undefined;
    const timer = setInterval(() => {
      void bffRequest<Answer>(`/api/bff/cases/${encodeURIComponent(caseRef)}/clinical-requests/${encodeURIComponent(requestId)}`).then((result) => {
        if (!result.ok) return;
        setAnswer(result.data);
        if (result.data.state === 'taken') setPhase('taken');
        if (result.data.state === 'advised') setPhase('advised');
        if (result.data.state === 'returned') setPhase('returned');
      });
    }, POLL_MS);
    return () => clearInterval(timer);
  }, [caseRef, requestId, phase]);

  const call = async () => {
    if (why === null) {
      setError('Choose why you are asking.');
      return;
    }
    setBusy(true);
    setError(null);
    const result = await bffRequest<{ requestId: string }>(`/api/bff/cases/${encodeURIComponent(caseRef)}/clinical-requests`, {
      method: 'POST',
      body: { urgency, why },
    });
    setBusy(false);
    if (!result.ok) {
      setError('Could not send the request. Try again.');
      return;
    }
    setRequestId(result.data.requestId);
    setPhase('waiting');
  };

  const onKey = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === 'Escape') {
      event.preventDefault();
      onClose();
      return;
    }
    if (event.key !== 'Tab') return;
    const focusable = Array.from(dialogRef.current?.querySelectorAll<HTMLElement>('button:not([disabled]), a[href], input, textarea, select') ?? []);
    if (focusable.length === 0) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first?.focus();
    } else if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last?.focus();
    }
  };

  const noneAvailable = available === 0;

  return (
    <div className={styles.stack}>
      <div role="dialog" aria-modal="true" aria-labelledby={titleId} ref={dialogRef} onKeyDown={onKey} className={styles.section}>
        <h2 id={titleId} ref={headingRef} tabIndex={-1} className={styles.heading}>Ask a clinical advisor</h2>
        <p className={styles.footer}>Escalate</p>

        <section aria-label="Case summary" className={styles.section}>
          <p>{`${summary.ageBand} · ${summary.district} · ${summary.needs.join(', ')} · ${summary.within}`}</p>
          <p>{`NEWS2 ${summary.news2} · Frailty scale ${summary.frailtyScale} · Options shown: ${optionsShown}`}</p>
        </section>

        {phase === 'ask' ? (
          <>
            <fieldset className={styles.plain}>
              <legend className={styles.legend}>How soon do you need them?</legend>
              <div className={styles.group}>
                {(['now', 'within-15-min'] as const).map((value) => (
                  <OptionButton key={value} selected={urgency === value} onSelect={() => setUrgency(value)} dataEl={`ADV-CLIN-URGENCY-${value.toUpperCase()}`}>
                    {URGENCY_LABELS[value]}
                  </OptionButton>
                ))}
              </div>
            </fieldset>
            <fieldset className={styles.plain}>
              <legend className={styles.legend}>Why are you asking?</legend>
              <div className={styles.group}>
                {WHY_CHOICES.map((value) => (
                  <OptionButton key={value} selected={why === value} onSelect={() => setWhy(value)}>
                    {WHY_LABELS[value]}
                  </OptionButton>
                ))}
              </div>
            </fieldset>
            <p>
              {available === null ? '' : noneAvailable ? '' : `${available} clinical advisor${available === 1 ? '' : 's'} available`}
            </p>
            {noneAvailable ? <p role="alert" className={styles.error}>{NONE_AVAILABLE}</p> : null}
            <p className={styles.footer}>The case summary goes with the call. No name is sent.</p>
            {error ? <p role="alert" className={styles.error}>{error}</p> : null}
            <div className={styles.actions}>
              <Button variant="primary" busy={busy} disabled={noneAvailable} onClick={call} dataEl="ADV-CLIN-CALL-BTN">Call clinical advisor</Button>
              <Button variant="secondary" onClick={onClose} dataEl="ADV-CLIN-CANCEL-BTN">Cancel</Button>
            </div>
          </>
        ) : null}

        {phase === 'waiting' ? <p role="status">Waiting for a clinical advisor</p> : null}
        {phase === 'taken' && answer?.takenByRole !== undefined && answer.takenAt !== undefined ? (
          <p role="status">{`Taken by ${answer.takenByRole} at ${clock(answer.takenAt)}`}</p>
        ) : null}
        {phase === 'advised' && answer?.advice !== undefined ? (
          <>
            <p role="status">{`Advice: ${ADVICE_CHOICE_LABEL(answer.advice)}. Reason: ${REASON_TEXT(answer.reason ?? 'other')}.`}</p>
            <div className={styles.actions}>
              <Button variant="primary" onClick={onClose} dataEl="ADV-CLIN-CLOSE-BTN">Close</Button>
            </div>
          </>
        ) : null}
      </div>
    </div>
  );
}


