'use client';

import { useId, useState, type ReactNode } from 'react';
import { Loading, Skeleton } from '@/components/ui/Skeleton';
import { bffPost } from '@/lib/bff/client';
import { callbackFormError, parseOverview } from '@/lib/registration/model';
import type { CallBackResult } from '@/lib/registration/types';
import styles from './CheckStep.module.css';
import { useRead } from '@/lib/bff/useRead';

// Check 1 of 4: call the service back (W29, ui-screens ApprovalWeb1 screen 4; boards Rev1 and RvP2). The number to
// call is the one from the register, and only that one; on a phone, Phone is a tel: link to it and the one primary
// action. The directory's name comes from tenant configuration, sent by the back end with the overview; nothing
// here names an organisation. The check is a card in the stage area: a level 2 heading, the page keeps its own.

const RESULTS: ReadonlyArray<{ value: CallBackResult; label: string }> = [
  { value: 'confirmed', label: 'Confirmed' },
  { value: 'not-confirmed', label: 'Not confirmed' },
  { value: 'no-answer', label: 'No answer' },
];

const TITLE = 'Call the service back';

function Card({ headingId, eyebrow, children }: { headingId: string; eyebrow: string; children: ReactNode }) {
  return (
    <section className={styles.card} aria-labelledby={headingId}>
      <div>
        <p className={styles.eyebrow}>{eyebrow}</p>
        <h2 id={headingId} className={styles.title}>
          {TITLE}
        </h2>
      </div>
      {children}
    </section>
  );
}

function telHref(number: string): string {
  return `tel:${number.replace(/[^\d+]/g, '')}`;
}

export function CallBackCheck({ id }: { id: string }) {
  const read = useRead(`/api/bff/registrations/${encodeURIComponent(id)}`, parseOverview);
  const uid = useId();
  const headingId = `${uid}-title`;
  const resultId = `${uid}-result`;
  const [result, setResult] = useState<CallBackResult | null>(null);
  const [role, setRole] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);

  if (read.status === 'failed') {
    return (
      <Card headingId={headingId} eyebrow="Check 1 of 4">
        <p role="alert" className={styles.error}>
          <span aria-hidden="true">▲ </span>This check could not be loaded. Try again shortly.
        </p>
      </Card>
    );
  }
  if (read.status === 'loading') {
    return (
      <Card headingId={headingId} eyebrow="Check 1 of 4">
        <Loading label="Loading the call-back check.">
          <Skeleton shape="block" />
          <Skeleton shape="line" width="70%" />
        </Loading>
      </Card>
    );
  }
  const overview = read.data;

  const numberToCall = overview.callBack?.numberToCall;
  const directory = overview.callBack?.directoryName;
  const name = overview.registeredBy.name;
  const registrantRole = overview.registeredBy.role;
  const overviewHref = `/lead/registrations/${encodeURIComponent(id)}`;

  const save = async () => {
    if (result === null) {
      setError('Choose a result');
      return;
    }
    const found = callbackFormError(result, role);
    setError(found);
    if (found !== null || numberToCall === undefined) return;
    setBusy(true);
    setFailure(null);
    setSaved(false);
    const trimmed = role.trim();
    const answer = await bffPost(`/api/bff/registrations/${encodeURIComponent(id)}/callback`, {
      result,
      numberCalled: numberToCall,
      ...(trimmed !== '' ? { spokeToRole: trimmed } : {}),
    });
    setBusy(false);
    if (answer.ok) setSaved(true);
    else setFailure('The call-back could not be saved. Try again.');
  };

  return (
    <Card headingId={headingId} eyebrow={`Check 1 of 4 · ${overview.serviceName}`}>
      <p className={styles.callout}>
        Phone the number on the NHS register{directory ? ` or the ${directory}` : ''}. <strong>Do not use the number the applicant gave.</strong>
      </p>

      <dl className={styles.numbers}>
        <div className={styles.number}>
          <dt>Number from the register</dt>
          <dd>{numberToCall ?? 'Not on the register'}</dd>
        </div>
        <div className={styles.number}>
          <dt>Number the applicant gave</dt>
          <dd>{overview.callBack?.numberGiven ?? 'Not given'}</dd>
        </div>
      </dl>

      <ol className={styles.script}>
        <li>Ask for {name}, or the person in charge</li>
        <li>Ask: is {name} a {registrantRole} at {overview.serviceName}?</li>
        <li>Ask: did they register for Overwatch today?</li>
        <li>
          <strong>Do not talk about any patient</strong>
        </li>
      </ol>

      <div role="group" aria-labelledby={resultId} className={styles.group}>
        <span id={resultId} className={styles.label}>
          Result
        </span>
        <div className={styles.row}>
          {RESULTS.map((option) => (
            <button
              key={option.value}
              type="button"
              className={styles.chip}
              aria-pressed={result === option.value}
              onClick={() => setResult(option.value)}
              data-el={`LEAD-REG-CALLBACK-RESULT-${option.value.toUpperCase()}`}
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false" className={styles.mark}>
                <circle cx="12" cy="12" r="9" />
                {result === option.value ? <path d="M8 12.5l2.5 2.5L16 9.5" /> : null}
              </svg>
              {option.label}
            </button>
          ))}
        </div>
      </div>

      <div className={styles.field}>
        <label htmlFor={`callback-role-${id}`} className={styles.label}>
          Who you spoke to (role){result === 'confirmed' ? ' Required' : ''}
        </label>
        <input
          id={`callback-role-${id}`}
          className={styles.input}
          value={role}
          onChange={(e) => setRole(e.target.value)}
          aria-invalid={error === 'Enter who you spoke to'}
        />
        {error !== null ? (
          <p role="alert" className={styles.error}>
            <span aria-hidden="true">▲ </span>
            {error}
          </p>
        ) : null}
      </div>

      {result === 'no-answer' ? (
        <p className={styles.hint}>No answer? Try again, or ask the applicant for their line manager to confirm by email.</p>
      ) : null}

      {failure !== null ? (
        <p role="alert" className={styles.error}>
          <span aria-hidden="true">▲ </span>
          {failure}
        </p>
      ) : null}
      {saved ? (
        <p aria-live="polite" className={styles.saved}>
          <span>
            <span aria-hidden="true">✓ </span>Call-back saved.
          </span>
          <a className={styles.next} href={`${overviewHref}?step=scope`}>
            Next: check 2 of 4
          </a>
        </p>
      ) : null}

      <div className={styles.actions}>
        {numberToCall !== undefined ? (
          <a className={`${styles.primary} ${styles.phone}`} href={telHref(numberToCall)} data-el="LEAD-REG-CALLBACK-PHONE-LINK">
            Phone {numberToCall}
          </a>
        ) : null}
        <button
          type="button"
          className={`${styles.primary} ${styles.save}`}
          disabled={busy}
          aria-busy={busy ? 'true' : undefined}
          onClick={save}
          data-el="LEAD-REG-CALLBACK-SAVE-BTN"
        >
          Save result
        </button>
        <a className={styles.text} href={overviewHref}>
          Back
        </a>
      </div>
    </Card>
  );
}
