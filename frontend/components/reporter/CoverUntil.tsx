'use client';

import styles from './Reporter.module.css';

// How long a cover lasts (W37, W38, W8E, DEC-820): tonight, this week or until a date. The back end
// ends it at 23:59 on the last day and refuses one more than a fortnight ahead.

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
    <fieldset>
      <legend>Until</legend>
      {CHOICES.map((choice) => (
        <label key={choice.value} className={styles.question}>
          <input type="radio" name={name} value={choice.value} checked={until === choice.value} onChange={() => onUntil(choice.value)} />
          {` ${choice.label}`}
        </label>
      ))}
      {until === 'date' ? (
        <input type="date" aria-label="Cover until date" value={date} onChange={(event) => onDate(event.target.value)} className={styles.input} />
      ) : null}
    </fieldset>
  );
}
