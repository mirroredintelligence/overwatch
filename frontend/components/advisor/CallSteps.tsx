import styles from './CallSteps.module.css';

// The four steps of a call (W10), shown in the header of every case screen. The step before the
// current one is done; the current one carries aria-current="step". Done is a word as well as the
// tick, so the state is not carried by colour alone.

export type CallStep = 'needs' | 'options' | 'request' | 'outcome';

const STEPS: readonly { id: CallStep; label: string }[] = [
  { id: 'needs', label: 'Needs' },
  { id: 'options', label: 'Options' },
  { id: 'request', label: 'Request' },
  { id: 'outcome', label: 'Outcome' },
];

// [ASSUMED] The Needs wording: the canvas has none for this step (W10 prompt).
export const STEP_TEXT: Record<CallStep, { now: string; next: string }> = {
  needs: {
    now: 'Now: capture age, postcode, needs and how soon.',
    next: 'Next: see the options.',
  },
  options: {
    now: 'Now: compare the options and check the criteria.',
    next: 'Next: request a booking from the one you choose.',
  },
  request: {
    now: 'Now: waiting for UCR West to confirm. Phone prompt at 14:21.',
    next: 'Next: when they confirm, tell the caller.',
  },
  outcome: {
    now: 'Now: record what happened, then copy the summary.',
    next: 'Next: start the next call.',
  },
};

export type CallStepsProps = {
  current: CallStep;
  /** The "Now" line. Defaults to the wording for the current step. */
  now?: string;
  /** The "Next" line. Defaults to the wording for the current step. */
  next?: string;
};

export function CallSteps({ current, now, next }: CallStepsProps) {
  const currentIndex = STEPS.findIndex((step) => step.id === current);
  const text = STEP_TEXT[current];

  return (
    <div className={styles.steps}>
      <ol className={styles.list} aria-label="Call steps">
        {STEPS.map((step, index) => {
          const done = index < currentIndex;
          const isCurrent = step.id === current;
          return (
            <li
              key={step.id}
              className={styles.step}
              data-el={`ADV-STEP-${step.id.toUpperCase()}`}
              data-step={step.id}
              data-state={done ? 'done' : isCurrent ? 'current' : 'todo'}
              aria-current={isCurrent ? 'step' : undefined}
            >
              <span className={styles.label}>{step.label}</span>
              {done ? <span className={styles.done}> Done</span> : null}
            </li>
          );
        })}
      </ol>
      <p className={styles.now}>{now ?? text.now}</p>
      <p className={styles.next}>{next ?? text.next}</p>
    </div>
  );
}
