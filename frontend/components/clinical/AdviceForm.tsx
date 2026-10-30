'use client';

import { useId, useState, type FormEvent } from 'react';
import { Button } from '@/components/ui/Button';
import { OptionButton } from '@/components/ui/OptionButton';
import { ADVICE_CHOICES, ADVICE_LABELS, ADVICE_REASONS, NOTE_LIMIT, REASON_LABELS, validateAdvice } from '@/lib/clinical/advice';
import { bffRequest } from '@/lib/bff/browser';
import styles from '@/components/exec/Exec.module.css';

// What the advisor advises (W44, ClinicalAdvisor screen 6). The choice is required; the reason and the
// note are optional. The note is checked here and again by the back end: it names no patient.

export const SEND_FAILED = 'Could not send advice. Try again.';

export function AdviceForm({ requestId, onSent }: { requestId: string; onSent: () => void }) {
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
      setFailed(SEND_FAILED);
      return;
    }
    onSent();
  };

  return (
    <form className={styles.stack} onSubmit={submit} noValidate>
      <fieldset className={styles.plain}>
        <legend className={styles.legend}>What do you advise?</legend>
        <div className={styles.group}>
          {ADVICE_CHOICES.map((choice) => (
            <OptionButton key={choice} selected={advice === choice} onSelect={() => setAdvice(choice)} dataEl={`CLIN-ADVICE-${choice.toUpperCase()}`}>
              {ADVICE_LABELS[choice]}
            </OptionButton>
          ))}
        </div>
      </fieldset>
      <fieldset className={styles.plain}>
        <legend className={styles.legend}>Why? (optional)</legend>
        <div className={styles.group}>
          {ADVICE_REASONS.map((choice) => (
            <OptionButton key={choice} selected={reason === choice} onSelect={() => setReason(reason === choice ? null : choice)}>
              {REASON_LABELS[choice]}
            </OptionButton>
          ))}
        </div>
      </fieldset>
      <div className={styles.field}>
        <label htmlFor={noteId} className={styles.legend}>Note (optional)</label>
        <textarea
          id={noteId}
          className={styles.input}
          value={note}
          onChange={(event) => setNote(event.target.value)}
          rows={3}
          aria-describedby={`${noteId}-hint`}
        />
        <p id={`${noteId}-hint`} className={styles.footer}>
          {`Add a short note only if needed. No patient names. ${note.length} of ${NOTE_LIMIT}`}
        </p>
      </div>
      {errors.length > 0 ? (
        <div role="alert" className={styles.error}>
          {errors.map((message) => <p key={message}>{message}</p>)}
        </div>
      ) : null}
      {failed ? <p role="alert" className={styles.error}>{failed}</p> : null}
      <div className={styles.actions}>
        <Button variant="primary" type="submit" busy={busy} dataEl="CLIN-ADVICE-SEND-BTN">Send advice</Button>
      </div>
    </form>
  );
}
