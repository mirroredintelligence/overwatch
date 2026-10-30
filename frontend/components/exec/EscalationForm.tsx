'use client';

import { useId, useState, type FormEvent } from 'react';
import { Button } from '@/components/ui/Button';
import { OptionButton } from '@/components/ui/OptionButton';
import { ACK_CHOICES, QUIET_END, QUIET_START, type AlertPreferences } from '@/lib/exec/alertPrefs';
import { DEPUTY_REQUIRED, hasDeputy } from '@/lib/exec/savePreferences';
import styles from './Exec.module.css';

// Quiet hours, the acknowledgement window and the deputy (W39, ExecApp2 screen 6). The ladder is you,
// then your deputy, then the shift lead by phone (U34 sends it; this screen only names it).

export type EscalationValues = Pick<AlertPreferences, 'quietHours' | 'quietCriticalOnly' | 'ackMinutes' | 'deputy'>;

type Props = {
  initial: EscalationValues;
  busy: boolean;
  onSave: (values: EscalationValues) => void;
  /** A failure from the last save, shown above the button. */
  error?: string | null;
};

const QUIET_LABEL = `${QUIET_START} to ${QUIET_END}`;

export function EscalationForm({ initial, busy, onSave, error = null }: Props) {
  const [quiet, setQuiet] = useState(initial.quietHours !== null);
  const [criticalOnly, setCriticalOnly] = useState(initial.quietCriticalOnly);
  const [ackMinutes, setAckMinutes] = useState(initial.ackMinutes);
  const [deputy, setDeputy] = useState(initial.deputy);
  const [deputyError, setDeputyError] = useState(false);
  const deputyId = useId();
  const errorId = useId();

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!hasDeputy({ deputy })) {
      setDeputyError(true);
      return;
    }
    setDeputyError(false);
    onSave({
      quietHours: quiet ? { start: QUIET_START, end: QUIET_END } : null,
      quietCriticalOnly: quiet ? criticalOnly : initial.quietCriticalOnly,
      ackMinutes,
      deputy: deputy.trim(),
    });
  };

  return (
    <form className={styles.stack} onSubmit={submit} noValidate>
      <fieldset className={styles.plain}>
        <legend className={styles.legend}>Quiet hours</legend>
        <div className={styles.group}>
          <OptionButton selected={quiet} onSelect={() => setQuiet(true)} dataEl="EXEC-ESC-QUIET-2200-0600">
            {QUIET_LABEL}
          </OptionButton>
          <OptionButton selected={!quiet} onSelect={() => setQuiet(false)} dataEl="EXEC-ESC-QUIET-NONE">
            None
          </OptionButton>
        </div>
      </fieldset>

      {quiet ? (
        <fieldset className={styles.plain}>
          <legend className={styles.legend}>During quiet hours, alert me about</legend>
          <div className={styles.group}>
            <OptionButton selected={criticalOnly} onSelect={() => setCriticalOnly(true)} dataEl="EXEC-ESC-QUIET-CRITICAL">
              Critical only
            </OptionButton>
            <OptionButton selected={!criticalOnly} onSelect={() => setCriticalOnly(false)} dataEl="EXEC-ESC-QUIET-EVERYTHING">
              Everything
            </OptionButton>
          </div>
        </fieldset>
      ) : null}

      <fieldset className={styles.plain}>
        <legend className={styles.legend}>If I do not acknowledge within</legend>
        <div className={styles.group}>
          {ACK_CHOICES.map((minutes) => (
            <OptionButton
              key={minutes}
              selected={ackMinutes === minutes}
              onSelect={() => setAckMinutes(minutes)}
              dataEl={`EXEC-ESC-ACK-${minutes}`}
            >
              {`${minutes} min`}
            </OptionButton>
          ))}
        </div>
      </fieldset>

      <div className={styles.field}>
        <label htmlFor={deputyId} className={styles.legend}>Then alert</label>
        <input
          id={deputyId}
          className={styles.input}
          type="text"
          value={deputy}
          onChange={(event) => setDeputy(event.target.value)}
          aria-invalid={deputyError ? 'true' : undefined}
          aria-describedby={deputyError ? errorId : undefined}
          autoComplete="off"
          data-el="EXEC-ESC-DEPUTY-INPUT"
        />
        {deputyError ? (
          <p id={errorId} className={styles.error} role="alert">{DEPUTY_REQUIRED}</p>
        ) : null}
        <p className={styles.footer}>The ladder: you, then your deputy, then the shift lead by phone.</p>
      </div>

      {error ? <p className={styles.error} role="alert">{error}</p> : null}

      <div className={styles.actions}>
        <Button variant="primary" type="submit" busy={busy} dataEl="EXEC-ESC-SAVE-BTN">
          Save
        </Button>
      </div>
    </form>
  );
}
