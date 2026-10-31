import type { ReactNode } from 'react';
import styles from './Parts.module.css';

// A numbered list whose items are cards with a title and a line under it (artboards OnboardReporter1
// "Welcome" and "Add to home screen", OnboardReporter2 "Turn on notifications"). It is an ordered list, so
// the order is said to a screen reader; the number in the circle repeats it for the eye and is hidden.

export type StepCard = { key: string; title: ReactNode; hint?: ReactNode };

export function StepCards({ steps, label }: { steps: readonly StepCard[]; label?: string }) {
  return (
    <ol className={styles.steps} aria-label={label}>
      {steps.map((step, index) => (
        <li key={step.key} className={styles.step}>
          <span className={styles.stepNumber} aria-hidden="true">
            {index + 1}
          </span>
          <span className={styles.stepBody}>
            <span className={styles.stepTitle}>{step.title}</span>
            {step.hint === undefined ? null : <span className={styles.stepHint}>{step.hint}</span>}
          </span>
        </li>
      ))}
    </ol>
  );
}
