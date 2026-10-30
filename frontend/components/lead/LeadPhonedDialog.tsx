'use client';

import { useId, useRef, useState, type FormEvent } from 'react';
import { Button } from '@/components/ui/Button';
import { Dialog } from '@/components/ui/Dialog';
import { OptionButton } from '@/components/ui/OptionButton';
import { leadPost, newIdempotencyKey } from '@/lib/lead/browser';
import { MAX_FIGURE, type Said } from '@/lib/lead/phonedBody';
import styles from '@/components/advisor/dialog-body.module.css';

// The shift lead's "Enter what they told me by phone" (W17, W42, W43; DEC-920). A service's answer with no case:
// what it said on the phone and how many it can take. The lead's answer is recorded as advisor-phoned, through
// the BFF's phoned route. "Not accepting" carries no figure. A form that is refused stays open, and says so.

const ANSWERS: readonly { said: Said; label: string; id: string }[] = [
  { said: 'accepting', label: 'Accepting', id: 'ACCEPTING' },
  { said: 'limited', label: 'Limited', id: 'LIMITED' },
  { said: 'not-accepting', label: 'Not accepting', id: 'NOT-ACCEPTING' },
];

const ERROR = 'Enter how many they can take, as a whole number';
const SAVE_FAILED = 'The position could not be saved. Try again.';
const WHOLE = /^\d+$/;

export type LeadPhonedDialogProps = {
  open: boolean;
  serviceId: string;
  serviceName: string;
  onClose: () => void;
  /** Called once the back end has recorded the answer, before the dialog closes. */
  onRecorded?: () => void;
};

export function LeadPhonedDialog({ open, serviceId, serviceName, onClose, onRecorded }: LeadPhonedDialogProps) {
  if (!open) return null;
  return <OpenLeadPhonedDialog serviceId={serviceId} serviceName={serviceName} onClose={onClose} onRecorded={onRecorded} />;
}

// The form's state lives in its own component, so opening the dialog starts it empty.
function OpenLeadPhonedDialog({ serviceId, serviceName, onClose, onRecorded }: Omit<LeadPhonedDialogProps, 'open'>) {
  const [said, setSaid] = useState<Said | null>(null);
  const [text, setText] = useState('');
  const [error, setError] = useState(false);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const keyRef = useRef<string | null>(null);
  const valueId = useId();

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (said === null || busy) return;
    let value: number | undefined;
    if (said !== 'not-accepting') {
      const figure = Number(text);
      if (!WHOLE.test(text) || figure > MAX_FIGURE) {
        setError(true);
        return;
      }
      value = figure;
    }
    setError(false);
    setFailed(false);
    setBusy(true);
    keyRef.current ??= newIdempotencyKey();
    const body = value === undefined ? { said } : { said, value };
    const result = await leadPost(`/api/bff/lead/services/${encodeURIComponent(serviceId)}/phoned`, body, keyRef.current);
    setBusy(false);
    if (!result.ok) {
      setFailed(true);
      return;
    }
    keyRef.current = null;
    onRecorded?.();
    onClose();
  }

  return (
    <Dialog title="Enter what they told me by phone" sub={serviceName} dataEl="LEAD-PHONED-DIALOG" onClose={onClose}>
      <form onSubmit={(event) => void save(event)} noValidate>
        <fieldset className={styles.group}>
          <legend className={styles.legend}>{`What did ${serviceName} tell you?`}</legend>
          {ANSWERS.map((answer) => (
            <OptionButton
              key={answer.said}
              selected={said === answer.said}
              onSelect={() => setSaid(answer.said)}
              dataEl={`LEAD-PHONED-${answer.id}`}
            >
              {answer.label}
            </OptionButton>
          ))}
        </fieldset>

        {said === null || said === 'not-accepting' ? null : (
          <div className={styles.field}>
            <label className={styles.label} htmlFor={valueId}>
              How many can they take?
            </label>
            <input
              id={valueId}
              className={styles.input}
              type="text"
              inputMode="numeric"
              autoComplete="off"
              value={text}
              onChange={(event) => setText(event.target.value)}
              aria-invalid={error ? 'true' : undefined}
              aria-describedby={error ? `${valueId}-error` : undefined}
            />
            {error ? (
              <p id={`${valueId}-error`} className={styles.error}>
                {ERROR}
              </p>
            ) : null}
          </div>
        )}

        <p className={styles.note}>Updates the board for everyone. Recorded as “advisor phoned”.</p>
        {failed ? (
          <p role="alert" className={styles.error}>
            {SAVE_FAILED}
          </p>
        ) : null}

        <div className={styles.actions}>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" type="submit" busy={busy} disabled={said === null} dataEl="LEAD-PHONED-SAVE-BTN">
            Save position
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
