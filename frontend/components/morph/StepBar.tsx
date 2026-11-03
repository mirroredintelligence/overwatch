import styles from './StepBar.module.css';

// The numbered pills of a guided flow (boards/lead/AddService.dc.html, Suspend, ScreenPair, OwnerReview). In the
// product the pills are the way back to steps already reached; a step not reached yet is shown, not pressable.
// The current one is aria-current="step". The name of each pill carries the number and the state in words.

export type Step = {
  label: string;
  /** Where a visited step goes, when each step has an address (`?step=1`). Without it the pill is a button. */
  href?: string;
};

export type StepBarProps = {
  /** The accessible name of the nav, for example "Setup steps". */
  label: string;
  steps: readonly Step[];
  /** The current step, from 0. */
  current: number;
  /** The furthest step reached so far. Default: the current one. Steps up to it can be gone back to. */
  reached?: number;
  onSelect?: (index: number) => void;
};

type State = 'done' | 'current' | 'visited' | 'ahead';

export function StepBar({ label, steps, current, reached, onSelect }: StepBarProps) {
  const here = Math.min(Math.max(Math.trunc(current), 0), Math.max(steps.length - 1, 0));
  const furthest = Math.max(reached === undefined ? here : Math.trunc(reached), here);
  return (
    <nav aria-label={label} className={styles.bar}>
      <ol className={styles.list}>
        {steps.map((step, i) => {
          const state: State = i === here ? 'current' : i < here ? 'done' : i <= furthest ? 'visited' : 'ahead';
          const words = { done: 'done', current: 'current', visited: 'visited', ahead: 'not reached yet' }[state];
          const content = (
            <>
              <span className={styles.num} aria-hidden="true">
                {state === 'done' ? '✓' : i + 1}
              </span>
              <span className={styles.text} aria-hidden="true">
                {step.label}
              </span>
              <span className={styles.sr}>{`Step ${i + 1}, ${words}: ${step.label}`}</span>
            </>
          );
          const pressable = state === 'done' || state === 'visited';
          return (
            <li key={i} className={styles.item}>
              {pressable && step.href ? (
                <a className={styles.pill} data-state={state} href={step.href} onClick={onSelect ? () => onSelect(i) : undefined}>
                  {content}
                </a>
              ) : pressable && onSelect ? (
                <button type="button" className={styles.pill} data-state={state} onClick={() => onSelect(i)}>
                  {content}
                </button>
              ) : (
                <span className={styles.pill} data-state={state} aria-current={state === 'current' ? 'step' : undefined}>
                  {content}
                </span>
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
