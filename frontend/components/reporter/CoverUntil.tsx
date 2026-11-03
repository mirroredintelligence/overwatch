'use client';

import styles from './CoverUntil.module.css';

// How long a cover lasts (W37, W38, W8E, DEC-820): tonight, this week or until a date. The back end
// ends it at 23:59 on the last day and refuses one more than a fortnight ahead.
// Drawn as the chips on artboard B7 (3); each is still a real radio button, so the arrow keys work.
// The chosen chip is filled and carries a tick, so it is not told apart by colour alone.

export type Until = 'tonight' | 'this-week' | 'date';

const CHOICES: { value: Until; label: string }[] = [
  { value: 'tonight', label: 'Tonight' },
  { value: 'this-week', label: 'This week' },
  { value: 'date', label: 'A date' },
];

export const NEEDS_DATE = 'Choose the last day of the cover.';

/** The body part for the choice, or null when a date is chosen and none is given. */
export function untilBody(until: Until, date: string): { until: Until; date?: string } | null {
  if (until !== 'date') return { until };
  return /^\d{4}-\d{2}-\d{2}$/.test(date) ? { until, date } : null;
}

type Props = { until: Until; date: string; onUntil: (until: Until) => void; onDate: (date: string) => void; name: string };

export function CoverUntil({ until, date, onUntil, onDate, name }: Props) {
  return (
    <fieldset className={styles.fieldset}>
      <legend className={styles.legend}>Until</legend>
      <div className={styles.chips}>
        {CHOICES.map((choice) => {
          const selected = until === choice.value;
          return (
            <label key={choice.value} className={styles.chip} data-chip="" data-selected={selected ? 'true' : 'false'}>
              <input className={styles.radio} type="radio" name={name} value={choice.value} checked={selected} onChange={() => onUntil(choice.value)} />
              {selected ? (
                <svg width="16" height="16" viewBox="0 0 20 20" aria-hidden="true" focusable="false">
                  <path d="M4 10.5l4 4 8-9" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              ) : null}
              {choice.label}
            </label>
          );
        })}
      </div>
      {until === 'date' ? (
        <input type="date" aria-label="Cover until date" value={date} onChange={(event) => onDate(event.target.value)} className={styles.date} />
      ) : null}
    </fieldset>
  );
}
