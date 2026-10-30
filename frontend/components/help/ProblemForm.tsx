'use client';

import { useId, useState, type FormEvent } from 'react';
import { Button } from '@/components/ui/Button';
import { OptionButton } from '@/components/ui/OptionButton';
import { bffRequest } from '@/lib/bff/browser';
import { looksLikePatientData } from '@/lib/forms/patientDataHint';
import { checkProblem, REPORT_LIMIT, type ProblemKind } from '@/lib/help/report';
import exec from '@/components/exec/Exec.module.css';
import styles from './Help.module.css';

// Something is wrong with the tool (W46, TrainingPhone screen 4). The report says what kind of problem
// and which page it was on; it goes to nobody else.

const KINDS: readonly { value: ProblemKind; label: string }[] = [
  { value: 'screen-slow', label: 'A screen is slow' },
  { value: 'button-does-not-work', label: 'A button does not work' },
  { value: 'figure-looks-wrong', label: 'A figure looks wrong' },
  { value: 'something-else', label: 'Something else' },
];

export const SEND_FAILED = 'We could not send your report. Try again later.';

export function ProblemForm({ from }: { from: string }) {
  const [kind, setKind] = useState<ProblemKind | null>(null);
  const [text, setText] = useState('');
  const [errors, setErrors] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState<string | null>(null);
  const [sent, setSent] = useState(false);
  const textId = useId();

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const checked = checkProblem({ kind, route: from, text });
    if (!checked.ok) {
      setErrors(checked.errors);
      return;
    }
    setErrors([]);
    setBusy(true);
    setFailed(null);
    const result = await bffRequest('/api/bff/help/problems', { method: 'POST', body: checked.value });
    setBusy(false);
    if (!result.ok) {
      setFailed(SEND_FAILED);
      return;
    }
    setSent(true);
  };

  if (sent) {
    return (
      <section className={exec.stack} aria-labelledby="report-sent">
        <h2 id="report-sent" className={exec.heading}>Thanks. We have your report.</h2>
      </section>
    );
  }

  return (
    <form className={exec.stack} onSubmit={submit} noValidate>
      <fieldset className={exec.plain}>
        <legend className={exec.legend}>Choose one</legend>
        <div className={exec.group}>
          {KINDS.map((choice) => (
            <OptionButton
              key={choice.value}
              selected={kind === choice.value}
              onSelect={() => setKind(choice.value)}
              dataEl={`HELP-PROBLEM-KIND-${choice.value.toUpperCase()}`}
            >
              {choice.label}
            </OptionButton>
          ))}
        </div>
      </fieldset>

      <div className={exec.field}>
        <label htmlFor={textId} className={exec.legend}>Tell us more (optional)</label>
        <textarea
          id={textId}
          className={exec.input}
          rows={3}
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

      {errors.length > 0 ? <p role="alert" className={exec.error}>{errors.join(' ')}</p> : null}
      {failed ? <p role="alert" className={exec.error}>{failed}</p> : null}

      <div className={exec.actions}>
        <Button variant="primary" type="submit" busy={busy} dataEl="HELP-PROBLEM-SEND-BTN">Send report</Button>
      </div>
    </form>
  );
}
