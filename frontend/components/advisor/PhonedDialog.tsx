'use client';

import { useState } from 'react';
import { Button } from '@/components/ui/Button';
import { Dialog } from '@/components/ui/Dialog';
import { OptionButton } from '@/components/ui/OptionButton';
import { bffFetch, newIdempotencyKey } from '@/lib/advisor/browser';
import type { Said } from '@/lib/advisor/service-api';
import styles from './dialog-body.module.css';

// "I phoned" (W14): what the service said on the phone. The answer updates the board for everyone,
// so it is recorded as the advisor's, never as the service's own report. A "not accepting" answer
// sends 0 and hides the number.

const ANSWERS: readonly { said: Said; label: string; id: string }[] = [
  { said: 'accepting', label: 'Accepting', id: 'ACCEPTING' },
  { said: 'limited', label: 'Limited', id: 'LIMITED' },
  { said: 'not-accepting', label: 'Not accepting', id: 'NOT-ACCEPTING' },
];

const ERROR = 'Enter how many they can take, as a whole number';
const WHOLE = /^\d+$/;
const SAVE_FAILED = 'The position could not be saved. Try again.';

export type PhonedDialogProps = {
  caseRef: string;
  serviceId: string;
  serviceName: string;
  onSaved: () => void;
  onClose: () => void;
};

export function PhonedDialog({ caseRef, serviceId, serviceName, onSaved, onClose }: PhonedDialogProps) {
  const [said, setSaid] = useState<Said | null>(null);
  const [text, setText] = useState('');
  const [error, setError] = useState(false);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);

  async function save() {
    if (said === null || busy) return;
    let value = 0;
    if (said !== 'not-accepting') {
      if (!WHOLE.test(text)) {
        setError(true);
        return;
      }
      value = Number(text);
    }
    setError(false);
    setFailed(false);
    setBusy(true);
    const reply = await bffFetch<{ recorded: boolean }>(
      `/api/bff/services/${encodeURIComponent(serviceId)}/phoned`,
      { method: 'POST', body: { caseRef, said, value }, idempotencyKey: newIdempotencyKey() },
    );
    if (reply.ok) {
      onSaved();
      onClose();
      return;
    }
    setBusy(false);
    setFailed(true);
  }

  return (
    <Dialog title="I phoned" sub={serviceName} dataEl="ADV-PHONED-DIALOG" onClose={onClose}>
      <fieldset className={styles.group}>
        <legend className={styles.legend}>{`What did ${serviceName} tell you?`}</legend>
        {ANSWERS.map((answer) => (
          <OptionButton
            key={answer.said}
            selected={said === answer.said}
            onSelect={() => setSaid(answer.said)}
            dataEl={`ADV-PHONED-${answer.id}`}
          >
            {answer.label}
          </OptionButton>
        ))}
      </fieldset>

      {said === null || said === 'not-accepting' ? null : (
        <div className={styles.field}>
          <label className={styles.label} htmlFor="phoned-value">
            How many can they take?
          </label>
          <input
            id="phoned-value"
            className={styles.input}
            type="text"
            inputMode="numeric"
            autoComplete="off"
            value={text}
            onChange={(event) => setText(event.target.value)}
            aria-invalid={error ? 'true' : undefined}
            aria-describedby={error ? 'phoned-value-error' : undefined}
          />
          {error ? (
            <p id="phoned-value-error" className={styles.error}>
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
        <Button variant="primary" busy={busy} disabled={said === null} dataEl="ADV-PHONED-SAVE-BTN" onClick={save}>
          Save position
        </Button>
      </div>
    </Dialog>
  );
}
