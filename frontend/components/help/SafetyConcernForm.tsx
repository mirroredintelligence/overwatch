'use client';

import { useId, useState, type FormEvent } from 'react';
import { Button } from '@/components/ui/Button';
import { OptionButton } from '@/components/ui/OptionButton';
import { bffRequest } from '@/lib/bff/browser';
import { looksLikePatientData } from '@/lib/forms/patientDataHint';
import { checkSafetyConcern, REPORT_LIMIT, type SafetyCategory } from '@/lib/help/report';
import exec from '@/components/exec/Exec.module.css';
import styles from './Help.module.css';

// Report a safety concern (W46, SafetyConcern screens 1 to 4). It goes to the clinical safety officer.
// The text is the patient-data warning's only input; the server is the real guard.

const CATEGORIES: readonly { value: SafetyCategory; label: string }[] = [
  { value: 'wrong-service-shown', label: 'Wrong service shown' },
  { value: 'out-of-date-criteria', label: 'Out-of-date criteria' },
  { value: 'wrong-status-on-board', label: 'Wrong status on the board' },
  { value: 'message-went-to-wrong-place', label: 'A message went to the wrong place' },
  { value: 'something-else', label: 'Something else' },
];

export const SEND_FAILED = 'Could not send your concern. Try again.';
const ERRORS_TITLE = 'Please fix these before sending';

export function SafetyConcernForm() {
  const [category, setCategory] = useState<SafetyCategory | null>(null);
  const [reference, setReference] = useState('');
  const [text, setText] = useState('');
  const [errors, setErrors] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState<string | null>(null);
  const [sent, setSent] = useState<string | null>(null);
  const referenceId = useId();
  const textId = useId();

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const checked = checkSafetyConcern({ category, reference, text });
    if (!checked.ok) {
      setErrors(checked.errors);
      return;
    }
    setErrors([]);
    setBusy(true);
    setFailed(null);
    const result = await bffRequest<{ reference: string }>('/api/bff/help/safety-concerns', { method: 'POST', body: checked.value });
    setBusy(false);
    if (!result.ok) {
      setFailed(SEND_FAILED);
      return;
    }
    setSent(result.data.reference);
  };

  if (sent !== null) {
    return (
      <section className={exec.stack} aria-labelledby="concern-sent">
        <h2 id="concern-sent" className={exec.heading}>{`Concern ${sent} sent`}</h2>
        <p>A clinical safety officer will review it. You will be told when it has been looked at.</p>
        <p>If someone is at risk now, phone the coordination team or follow local procedure.</p>
      </section>
    );
  }

  return (
    <form className={exec.stack} onSubmit={submit} noValidate>
      {errors.length > 0 ? (
        <div role="alert" className={exec.error}>
          <p>{ERRORS_TITLE}</p>
          <ul>
            {errors.map((message) => <li key={message}>{message}</li>)}
          </ul>
        </div>
      ) : null}

      <fieldset className={exec.plain}>
        <legend className={exec.legend}>What is it about?</legend>
        <div className={exec.group}>
          {CATEGORIES.map((choice) => (
            <OptionButton
              key={choice.value}
              selected={category === choice.value}
              onSelect={() => setCategory(choice.value)}
              dataEl={`HELP-SAFETY-CAT-${choice.value.toUpperCase()}`}
            >
              {choice.label}
            </OptionButton>
          ))}
        </div>
        <p className={styles.counter}>Categories are to be agreed with the clinical safety officer.</p>
      </fieldset>

      <div className={exec.field}>
        <label htmlFor={referenceId} className={exec.legend}>Case or booking reference (optional)</label>
        <input id={referenceId} className={exec.input} type="text" value={reference} onChange={(e) => setReference(e.target.value)} autoComplete="off" />
      </div>

      <div className={exec.field}>
        <label htmlFor={textId} className={exec.legend}>What happened?</label>
        <textarea
          id={textId}
          className={exec.input}
          rows={4}
          value={text}
          onChange={(e) => setText(e.target.value)}
          aria-describedby={`${textId}-count`}
        />
        <p id={`${textId}-count`} className={styles.counter}>{`${text.length} of ${REPORT_LIMIT}`}</p>
        <p className={exec.footer}>No patient names or details.</p>
        {looksLikePatientData(text) ? (
          <p role="status" className={styles.hint}>This looks like it may contain patient details. Please remove them.</p>
        ) : null}
      </div>

      <section className={styles.warning} aria-label="Before you send">
        If someone is at risk now, phone the coordination team or follow local procedure first.
      </section>

      {failed ? <p role="alert" className={exec.error}>{failed}</p> : null}

      <div className={exec.actions}>
        <Button variant="primary" type="submit" busy={busy} dataEl="HELP-SAFETY-SEND-BTN">Send to the clinical safety officer</Button>
      </div>
    </form>
  );
}
