'use client';

import { useId, useState, type FormEvent } from 'react';
import { Button } from '@/components/ui/Button';
import { OptionButton } from '@/components/ui/OptionButton';
import { ACK_CHOICES, QUIET_END, QUIET_START, type AlertPreferences } from '@/lib/exec/alertPrefs';
import type { Leader } from '@/lib/exec/leaders';
import { DEPUTY_REQUIRED, hasDeputy } from '@/lib/exec/savePreferences';
import styles from './Exec.module.css';

// Quiet hours, the acknowledgement window and the deputy (W39, ExecApp2 screen 6). The ladder is you,
// then your deputy, then the shift lead by phone (U34 sends it; this screen only names it). The set-up flow
// gives it its own save. The settings page hides that save (showSave false) and saves the whole state itself,
// so the form reports each change through onChange.

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
  /** Each change as it is made, with the deputy trimmed. */
  onChange?: (values: EscalationValues) => void;
  /** Default true. False when the page has its own save for everything. */
  showSave?: boolean;
};

type Draft = {
  quiet: boolean;
  criticalOnly: boolean;
  ackMinutes: AlertPreferences['ackMinutes'];
  deputy: string;
};

const QUIET_LABEL = `${QUIET_START} to ${QUIET_END}`;

function valuesOf(draft: Draft, criticalOnlyWhenQuietOff: boolean): EscalationValues {
  return {
    quietHours: draft.quiet ? { start: QUIET_START, end: QUIET_END } : null,
    quietCriticalOnly: draft.quiet ? draft.criticalOnly : criticalOnlyWhenQuietOff,
    ackMinutes: draft.ackMinutes,
    deputy: draft.deputy.trim(),
  };
}

export function EscalationForm({ initial, busy, onSave, error = null, leaders, onChange, showSave = true }: Props) {
  const onList = Array.isArray(leaders) && leaders.some((leader) => leader.id === initial.deputy);
  const [draft, setDraft] = useState<Draft>({
    quiet: initial.quietHours !== null,
    criticalOnly: initial.quietCriticalOnly,
    ackMinutes: initial.ackMinutes,
    // A saved deputy who is no longer on the list is not carried over: another is chosen.
    deputy: Array.isArray(leaders) && !onList ? '' : initial.deputy,
  });
  const [deputyError, setDeputyError] = useState(false);
  const deputyId = useId();
  const errorId = useId();

  const edit = (next: Partial<Draft>) => {
    const updated = { ...draft, ...next };
    setDraft(updated);
    onChange?.(valuesOf(updated, initial.quietCriticalOnly));
  };

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!hasDeputy({ deputy: draft.deputy })) {
      setDeputyError(true);
      return;
    }
    setDeputyError(false);
    onSave(valuesOf(draft, initial.quietCriticalOnly));
  };

  return (
    <form className={styles.stack} onSubmit={submit} noValidate>
      <fieldset className={styles.plain}>
        <legend className={styles.legend}>Quiet hours</legend>
        <div className={styles.group}>
          <OptionButton selected={draft.quiet} onSelect={() => edit({ quiet: true })} dataEl="EXEC-ESC-QUIET-2200-0600">
            {QUIET_LABEL}
          </OptionButton>
          <OptionButton selected={!draft.quiet} onSelect={() => edit({ quiet: false })} dataEl="EXEC-ESC-QUIET-NONE">
            None
          </OptionButton>
        </div>
      </fieldset>

      {draft.quiet ? (
        <fieldset className={styles.plain}>
          <legend className={styles.legend}>During quiet hours, alert me about</legend>
          <div className={styles.group}>
            <OptionButton selected={draft.criticalOnly} onSelect={() => edit({ criticalOnly: true })} dataEl="EXEC-ESC-QUIET-CRITICAL">
              Critical only
            </OptionButton>
            <OptionButton selected={!draft.criticalOnly} onSelect={() => edit({ criticalOnly: false })} dataEl="EXEC-ESC-QUIET-EVERYTHING">
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
              selected={draft.ackMinutes === minutes}
              onSelect={() => edit({ ackMinutes: minutes })}
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
                value={draft.deputy}
                onChange={(event) => edit({ deputy: event.target.value })}
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
              value={draft.deputy}
              onChange={(event) => edit({ deputy: event.target.value })}
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

      {showSave ? (
        <div className={styles.actions}>
          <Button variant="primary" type="submit" busy={busy} dataEl="EXEC-ESC-SAVE-BTN">
            Save
          </Button>
        </div>
      ) : null}
    </form>
  );
}
