'use client';

import { useId, type ReactNode } from 'react';
import { AGE_BANDS, NEEDS, URGENCIES, type AgeCode, type NeedCode, type UrgencyCode } from '@/lib/advisor/codes';
import styles from './TriageCard.module.css';

// The triage card in the assistant thread (WS-TRI): the find form split into two steps. Step 1 is the age and the
// postcode (the parent supplies the postcode field); step 2 is the need and the timeframe. It is controlled: every
// value and every change belongs to the parent. There is no Find button: the parent starts the search itself.

export type TriageCardProps = {
  step: 'age' | 'need';
  age: AgeCode | null;
  needs: readonly NeedCode[];
  urgency: UrgencyCode | null;
  postcodeSlot: ReactNode; // age step only: the parent's label, PostcodePicker and help text
  canNext: boolean; // age step: an age is chosen and the postcode is a full one
  onAge: (code: AgeCode) => void;
  onToggleNeed: (code: NeedCode) => void;
  onUrgency: (code: UrgencyCode) => void;
  onNext: () => void;
};

const AGE_HINT = 'Choose an age and a full postcode';
const NEED_HINT = 'Results appear when you choose a need and a timeframe.';

// The tick is decorative and hidden from the accessible name, so a pressed chip keeps its label.
function Tick({ on }: { on: boolean }) {
  return on ? (
    <span className={styles.tick} aria-hidden="true">
      ✓
    </span>
  ) : null;
}

export function TriageCard(props: TriageCardProps) {
  const hintId = useId();

  if (props.step === 'age') {
    const { age, canNext, postcodeSlot, onAge, onNext } = props;
    return (
      <div className={styles.card}>
        <h3 className={styles.heading}>Step 1 of 2 · Age and postcode</h3>
        <fieldset className={styles.field}>
          <legend className={styles.legend}>Patient age</legend>
          <div className={styles.choices}>
            {AGE_BANDS.map((band) => (
              <button
                key={band.code}
                type="button"
                className={styles.choice}
                aria-pressed={age === band.code}
                onClick={() => onAge(band.code)}
              >
                <Tick on={age === band.code} />
                {band.label}
              </button>
            ))}
          </div>
        </fieldset>
        {postcodeSlot}
        <div className={styles.nextRow}>
          <button
            type="button"
            className={styles.next}
            aria-disabled={canNext ? undefined : true}
            aria-describedby={canNext ? undefined : hintId}
            onClick={() => {
              if (canNext) onNext();
            }}
          >
            Next
          </button>
          {canNext ? null : (
            <p id={hintId} className={styles.hint}>
              {AGE_HINT}
            </p>
          )}
        </div>
      </div>
    );
  }

  const { needs, urgency, onToggleNeed, onUrgency } = props;
  return (
    <div className={styles.card}>
      <h3 className={styles.heading}>Step 2 of 2 · Need and timeframe</h3>
      <fieldset className={styles.field}>
        <legend className={styles.legend}>Patient need</legend>
        <div className={styles.choices}>
          {NEEDS.map((need) => {
            const on = needs.includes(need.code);
            return (
              <button
                key={need.code}
                type="button"
                className={styles.choice}
                aria-pressed={on}
                onClick={() => onToggleNeed(need.code)}
              >
                <Tick on={on} />
                {need.label}
              </button>
            );
          })}
        </div>
      </fieldset>
      <fieldset className={styles.field}>
        <legend className={styles.legend}>Required timeframe</legend>
        <div className={styles.choices}>
          {URGENCIES.map((item) => {
            const on = urgency === item.code;
            return (
              <button
                key={item.code}
                type="button"
                className={styles.choice}
                aria-pressed={on}
                onClick={() => onUrgency(item.code)}
              >
                <Tick on={on} />
                {item.label}
              </button>
            );
          })}
        </div>
      </fieldset>
      <p className={styles.hint}>{NEED_HINT}</p>
    </div>
  );
}
