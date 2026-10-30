'use client';

import { useCallback, useEffect, useId, useRef, useState, type KeyboardEvent } from 'react';
import { Button } from '@/components/ui/Button';
import { OptionButton } from '@/components/ui/OptionButton';
import { ADVICE_LABELS, REASON_LABELS } from '@/lib/clinical/advice';
import { bffRequest } from '@/lib/bff/browser';
import styles from '@/components/exec/Exec.module.css';

// "Ask a clinical advisor" (W45, AdvisorActions and AdvisorDialogsPhone). A modal: focus moves to its
// heading when it opens and is kept inside it, Escape closes it, and focus goes back to the button that
// opened it. While a request waits it reads the request every five seconds and stops once advice arrives.
// The answer is the back end's read of the request (DEC-774): the advice, the reason and the clinician's
// note once given. A read that fails is said, never shown as "waiting" (DEC-855, H-514). The case summary
// is what the caller passed in (null when the case could not be read); the only other read is the count of
// advisors available.

/** What the case holds, for the dialog's two lines. A part that is not recorded is null, never made up. */
export type CaseSummary = {
  ageBand: string | null;
  district: string | null;
  needs: string[];
  within: string | null;
  news2: number | null;
  frailtyScale: number | null;
};

type Urgency = 'now' | 'within-15-min';
type Why = 'borderline-criteria' | 'unsure-of-urgency' | 'other';
type Phase = 'ask' | 'waiting' | 'taken' | 'advised';
type Answer = { state: 'waiting' | 'taken' | 'advised'; returnsAt?: string; advice?: string; reason?: string; note?: string; advisedAt?: string };

export const POLL_MS = 5_000;
export const READ_FAILED = 'The answer could not be read. Check again, or use the escalation route under local protocol.';
export const RETURNED = 'The clinical advisor did not act in time. Your request is back in the queue.';
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

function caseLine(summary: CaseSummary): string {
  return [summary.ageBand, summary.district, summary.needs.length > 0 ? summary.needs.join(', ') : null, summary.within]
    .filter((part): part is string => part !== null && part !== '')
    .join(' · ');
}

function scoreLine(summary: CaseSummary, optionsShown: number): string {
  return [
    summary.news2 === null ? null : `NEWS2 ${summary.news2}`,
    summary.frailtyScale === null ? null : `Frailty scale ${summary.frailtyScale}`,
    `Options shown: ${optionsShown}`,
  ]
    .filter((part): part is string => part !== null)
    .join(' · ');
}

export function AskClinicalDialog({
  caseRef,
  summary,
  optionsShown,
  onClose,
}: {
  caseRef: string;
  summary: CaseSummary | null;
  optionsShown: number;
  onClose: () => void;
}) {
  const [urgency, setUrgency] = useState<Urgency>('now');
  const [why, setWhy] = useState<Why | null>(null);
  const [available, setAvailable] = useState<number | null>(null);
  const [phase, setPhase] = useState<Phase>('ask');
  const [requestId, setRequestId] = useState<string | null>(null);
  const [answer, setAnswer] = useState<Answer | null>(null);
  const [readFailed, setReadFailed] = useState(false);
  const [returned, setReturned] = useState(false);
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

  // One read of the request. A failed read is kept as a failure; a taken request that reads as waiting
  // again has gone back to the queue (a lapsed lock reads as waiting, DEC-774 item 3).
  const read = useCallback(async () => {
    if (requestId === null) return;
    const result = await bffRequest<Answer>(`/api/bff/cases/${encodeURIComponent(caseRef)}/clinical-requests/${encodeURIComponent(requestId)}`);
    if (!result.ok) {
      setReadFailed(true);
      return;
    }
    setReadFailed(false);
    setAnswer(result.data);
    if (result.data.state === 'advised') setPhase('advised');
    else if (result.data.state === 'taken') {
      setReturned(false);
      setPhase('taken');
    } else {
      if (phase === 'taken') setReturned(true);
      setPhase('waiting');
    }
  }, [caseRef, requestId, phase]);

  // Poll the request while it waits or is taken; stop when the advice arrives.
  useEffect(() => {
    if (requestId === null || (phase !== 'waiting' && phase !== 'taken')) return undefined;
    const timer = setInterval(() => void read(), POLL_MS);
    return () => clearInterval(timer);
  }, [requestId, phase, read]);

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
          {summary === null ? (
            <p>The case summary could not be read.</p>
          ) : (
            <>
              {caseLine(summary) !== '' ? <p>{caseLine(summary)}</p> : null}
              <p>{scoreLine(summary, optionsShown)}</p>
            </>
          )}
          {summary === null ? <p>{`Options shown: ${optionsShown}`}</p> : null}
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

        {phase === 'waiting' || phase === 'taken' ? (
          <>
            {readFailed ? (
              <div role="alert" className={styles.error}>
                <p>{READ_FAILED}</p>
                <Button variant="secondary" onClick={() => void read()} dataEl="ADV-CLIN-CHECK-BTN">Check again</Button>
              </div>
            ) : null}
            {!readFailed && phase === 'waiting' && returned ? <p role="status">{RETURNED}</p> : null}
            {!readFailed && phase === 'waiting' ? <p role="status">Waiting for a clinical advisor</p> : null}
            {!readFailed && phase === 'taken' ? (
              <p role="status">
                {answer?.returnsAt === undefined
                  ? 'A clinical advisor has taken your request.'
                  : `A clinical advisor has taken your request. It returns to the queue at ${clock(answer.returnsAt)} if they do not act.`}
              </p>
            ) : null}
            <p className={styles.footer}>Keep this open until the advice arrives. It is not kept if you close it.</p>
            <div className={styles.actions}>
              <Button variant="secondary" onClick={onClose} dataEl="ADV-CLIN-CLOSE-BTN">Close</Button>
            </div>
          </>
        ) : null}
        {phase === 'advised' && answer?.advice !== undefined ? (
          <>
            <p role="status">{`Advice: ${ADVICE_CHOICE_LABEL(answer.advice)}.${answer.reason === undefined ? '' : ` Reason: ${REASON_TEXT(answer.reason)}.`}`}</p>
            {answer.note !== undefined ? <p>{`Note from the clinical advisor: ${answer.note}`}</p> : null}
            <div className={styles.actions}>
              <Button variant="primary" onClick={onClose} dataEl="ADV-CLIN-CLOSE-BTN">Close</Button>
            </div>
          </>
        ) : null}
      </div>
    </div>
  );
}


