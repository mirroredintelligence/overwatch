'use client';

import { useId, useState, type FormEvent, type ReactNode } from 'react';
import { ADVICE_CHOICES, adviceText, ADVICE_REASONS, NOTE_LIMIT, REASON_LABELS, validateAdvice } from '@/lib/clinical/advice';
import { bffRequest } from '@/lib/bff/browser';
import styles from './CaseView.module.css';

// What the advisor advises (W44, ClinicalAdvisor screen 6). The choice is required; the reason and the
// note are optional and sit behind "Why? (optional)". The note is checked here and again by the back
// end: it names no patient. `onSent` is given the advice as a sentence, for the confirmation. `after` is
// shown under the send button inside the same card (the call to the advisor).

export const SEND_FAILED = 'Could not send advice. Try again.';
export const NO_LONGER_YOURS = 'This request is no longer yours. It may have returned to the queue.';

export function AdviceForm({
  requestId,
  serviceName = null,
  onSent,
  after = null,
}: {
  requestId: string;
  serviceName?: string | null;
  onSent: (advice: string) => void;
  after?: ReactNode;
}) {
  const [advice, setAdvice] = useState<string | null>(null);
  const [reason, setReason] = useState<string | null>(null);
  const [note, setNote] = useState('');
  const [errors, setErrors] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState<string | null>(null);
  const noteId = useId();

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const checked = validateAdvice({ advice, reason: reason ?? undefined, note });
    if (!checked.ok) {
      setErrors(checked.errors);
      return;
    }
    setErrors([]);
    setBusy(true);
    setFailed(null);
    const result = await bffRequest(`/api/bff/clinical/requests/${encodeURIComponent(requestId)}/advice`, {
      method: 'POST',
      body: checked.value,
    });
    setBusy(false);
    if (!result.ok) {
      setFailed(result.status === 409 || result.status === 404 ? NO_LONGER_YOURS : SEND_FAILED);
      return;
    }
    onSent(adviceText(checked.value.advice, serviceName));
  };

  return (
    <form className={styles.form} onSubmit={submit} noValidate>
      <fieldset className={styles.fieldset}>
        <legend className={styles.legend}>What do you advise?</legend>
        <div className={styles.options}>
          {ADVICE_CHOICES.map((choice) => (
            <button
              key={choice}
              type="button"
              className={styles.opt}
              aria-pressed={advice === choice}
              onClick={() => setAdvice(choice)}
              data-el={`CLIN-ADVICE-${choice.toUpperCase()}`}
            >
              <span className={styles.radio} aria-hidden="true" />
              {adviceText(choice, serviceName)}
            </button>
          ))}
        </div>
      </fieldset>
      <details className={styles.more}>
        <summary>Why? (optional)</summary>
        <div className={styles.reasons} role="group" aria-label="Why?">
          {ADVICE_REASONS.map((choice) => (
            <button
              key={choice}
              type="button"
              className={`${styles.opt} ${styles.reasonOpt}`}
              aria-pressed={reason === choice}
              onClick={() => setReason(reason === choice ? null : choice)}
            >
              {REASON_LABELS[choice]}
            </button>
          ))}
        </div>
        <div className={styles.noteField}>
          <label htmlFor={noteId} className={styles.noteLabel}>Note (optional)</label>
          <textarea
            id={noteId}
            className={styles.note}
            value={note}
            onChange={(event) => setNote(event.target.value)}
            rows={3}
            aria-describedby={`${noteId}-hint`}
          />
          <p id={`${noteId}-hint`} className={styles.hint}>
            {`Add a short note only if needed. No patient names. ${note.length} of ${NOTE_LIMIT}`}
          </p>
        </div>
      </details>
      {errors.length > 0 ? (
        <div role="alert" className={styles.errors}>
          {errors.map((message) => <p key={message}>{message}</p>)}
        </div>
      ) : null}
      {failed ? <p role="alert" className={styles.errors}>{failed}</p> : null}
      <div className={styles.buttons}>
        <button type="submit" className={styles.send} disabled={busy} aria-busy={busy ? 'true' : undefined} data-el="CLIN-ADVICE-SEND-BTN">
          Send advice
        </button>
        {after}
      </div>
    </form>
  );
}
