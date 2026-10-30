'use client';

import { useId, useState, type FormEvent } from 'react';
import { Button } from '@/components/ui/Button';
import { OptionButton } from '@/components/ui/OptionButton';
import { ACK_CHOICES, QUIET_END, QUIET_START, type AlertPreferences } from '@/lib/exec/alertPrefs';
import type { Leader } from '@/lib/exec/leaders';
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
  /**
   * The leaders a deputy can be chosen from (DEC-776). Omitted: the deputy is typed. Null: the list could
   * not be read, so it is typed and the screen says why. A list, even an empty one: the deputy is chosen.
   */
  leaders?: Leader[] | null;
};

const QUIET_LABEL = `${QUIET_START} to ${QUIET_END}`;

export function EscalationForm({ initial, busy, onSave, error = null, leaders }: Props) {
  const [quiet, setQuiet] = useState(initial.quietHours !== null);
  const [criticalOnly, setCriticalOnly] = useState(initial.quietCriticalOnly);
  const [ackMinutes, setAckMinutes] = useState(initial.ackMinutes);
  const onList = Array.isArray(leaders) && leaders.some((leader) => leader.id === initial.deputy);
  // A saved deputy who is no longer on the list is not carried over: another is chosen.
  const [deputy, setDeputy] = useState(Array.isArray(leaders) && !onList ? '' : initial.deputy);
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
        {Array.isArray(leaders) ? (
          <>
            {leaders.length === 0 ? (
              <p>No other leader is set up to be your deputy yet. Ask your shift lead.</p>
            ) : (
              <select
                id={deputyId}
                className={styles.input}
                value={deputy}
                onChange={(event) => setDeputy(event.target.value)}
                aria-invalid={deputyError ? 'true' : undefined}
                aria-describedby={deputyError ? errorId : undefined}
                data-el="EXEC-ESC-DEPUTY-SELECT"
              >
                <option value="">Choose a leader</option>
                {leaders.map((leader) => (
                  <option key={leader.id} value={leader.id}>{leader.name}</option>
                ))}
              </select>
            )}
            {!onList && initial.deputy !== '' ? <p className={styles.error} role="status">Your saved deputy is no longer a leader. Choose another.</p> : null}
          </>
        ) : (
          <>
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
            {leaders === null ? <p className={styles.footer}>The list of leaders could not be read.</p> : null}
          </>
        )}
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
