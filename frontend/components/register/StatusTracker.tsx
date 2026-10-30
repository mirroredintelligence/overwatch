import type { ReactNode } from 'react';
import styles from './register.module.css';

// The tracker of a submitted registration (W27): five steps in order, the current one marked with
// aria-current="step". The current step is also said in words, not only by its place in the list.

export const TRACKER_STEPS = ['Submitted', 'Checks', 'Approval', 'Test notification', 'Live'] as const;
export type TrackerStep = (typeof TRACKER_STEPS)[number];

export function StatusTracker({ current, details }: { current: TrackerStep; details: Partial<Record<TrackerStep, ReactNode>> }) {
  return (
    <ol className={styles.tracker} aria-label="Registration progress">
      {TRACKER_STEPS.map((step) => (
        <li key={step} aria-current={step === current ? 'step' : undefined} className={step === current ? styles.trackerCurrent : styles.trackerStep}>
          <span className={styles.trackerLabel} data-step-label>
            {step}
          </span>
          {details[step] !== undefined ? <span className={styles.trackerDetail}>{details[step]}</span> : null}
        </li>
      ))}
    </ol>
  );
}
