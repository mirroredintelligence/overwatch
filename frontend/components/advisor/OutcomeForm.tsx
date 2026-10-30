'use client';

import { type FormEvent, useState } from 'react';
import { Button } from '@/components/ui/Button';
import { Chip } from '@/components/ui/Chip';
import { bffFetch, newIdempotencyKey } from '@/lib/advisor/browser';
import {
  BEST_FIT_REASONS,
  type BestFitCode,
  OUTCOMES,
  type OutcomeCode,
  TEXT_OUTCOMES,
  type TextOutcome,
} from '@/lib/advisor/outcome';
import styles from './finish.module.css';

// What happened on the call, and why the best fit was not used (W15). Saving closes the case: the
// outcome is recorded and the postcode and needs are no longer kept on the screen.

const SAVE_FAILED = 'The outcome could not be saved. Try again.';

export type OutcomeFormProps = {
  caseId: string;
  /** An outcome named in the address. Shown as text when it is one of the no-chip outcomes. */
  preselect: TextOutcome | null;
  /** Called with the time the close was recorded. */
  onClosed: (closedAt: string) => void;
};

type Chosen = OutcomeCode | TextOutcome | null;

export function OutcomeForm({ caseId, preselect, onClosed }: OutcomeFormProps) {
  const [outcome, setOutcome] = useState<Chosen>(preselect);
  const [bestFit, setBestFit] = useState<BestFitCode | null>(null);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const textOutcome = preselect !== null ? TEXT_OUTCOMES[preselect] : null;

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (outcome === null || busy) return;
    setBusy(true);
    setFailed(false);
    const body: Record<string, string> = { outcome };
    if (bestFit !== null) body.bestFitNotUsed = bestFit;
    const reply = await bffFetch<{ closedAt: string }>(`/api/bff/cases/${encodeURIComponent(caseId)}/outcome`, {
      method: 'POST',
      body,
      idempotencyKey: newIdempotencyKey(),
    });
    if (reply.ok) {
      onClosed(reply.body.closedAt);
      return;
    }
    setBusy(false);
    setFailed(true);
  }

  return (
    <form className={styles.screen} onSubmit={save} noValidate>
      <fieldset className={styles.group}>
        <legend className={styles.legend}>What happened?</legend>
        {textOutcome !== null ? (
          <p className={styles.text}>{textOutcome}</p>
        ) : (
          <div className={styles.chips}>
            {OUTCOMES.map((item) => (
              <Chip
                key={item.code}
                pressed={outcome === item.code}
                onPressedChange={() => setOutcome(item.code)}
                dataEl={`ADV-FIN-OUTCOME-${item.id}`}
              >
                {item.label}
              </Chip>
            ))}
          </div>
        )}
      </fieldset>

      <fieldset className={styles.group}>
        <legend className={styles.legend}>If the best fit was not used, why?</legend>
        <div className={styles.chips}>
          {BEST_FIT_REASONS.map((item) => (
            <Chip
              key={item.code}
              pressed={bestFit === item.code}
              onPressedChange={(on) => setBestFit(on ? item.code : null)}
              dataEl={`ADV-FIN-BEST-${item.id}`}
            >
              {item.label}
            </Chip>
          ))}
        </div>
      </fieldset>

      {failed ? (
        <p role="alert" className={styles.error}>
          {SAVE_FAILED}
        </p>
      ) : null}

      <div className={styles.actions}>
        <Button variant="neutral" href={`/advisor/case/${encodeURIComponent(caseId)}/options`}>
          Cancel
        </Button>
        <Button type="submit" variant="primary" busy={busy} disabled={outcome === null} dataEl="ADV-FIN-SAVE-BTN">
          Save outcome
        </Button>
      </div>
    </form>
  );
}
