import styles from './LadderTimeline.module.css';

// The chase ladder: what has been tried, in order (text, reminder, advisor phone task, escalation). An ordered
// list; each step's state is a shape AND words (done = tick, open = dashed ring, escalated = amber ring).
// `line` is the one-line form for a phone: "Text 12:00 done · Reminder 12:30 done · Phone task 13:00 not done ·
// Escalated to you".

export type LadderState = 'done' | 'open' | 'escalated';

export type LadderStep = {
  id: string;
  time: string;
  /** For a machine-readable time (the `time` element's dateTime). */
  at?: string;
  title: string;
  detail?: string;
  state: LadderState;
  /** The short name used in the one-line form. Defaults to the title. */
  short?: string;
};

const WORDS: Record<LadderState, string> = { done: 'Done', open: 'Not done', escalated: 'Needs you' };

export type LadderTimelineProps = {
  label: string;
  steps: readonly LadderStep[];
  variant?: 'full' | 'line';
  /** Replace the state words (for example { done: 'Sent' }). */
  stateWords?: Partial<Record<LadderState, string>>;
};

export function LadderTimeline({ label, steps, variant = 'full', stateWords }: LadderTimelineProps) {
  const words = { ...WORDS, ...stateWords };

  if (variant === 'line') {
    return (
      <ol className={styles.line} aria-label={label}>
        {steps.map((s) => (
          <li key={s.id} className={styles.lineItem} data-state={s.state}>
            {s.state === 'escalated' ? (
              <b>{s.short ?? s.title}</b>
            ) : (
              <>
                {s.short ?? s.title} {s.time} {words[s.state].toLowerCase()}
              </>
            )}
          </li>
        ))}
      </ol>
    );
  }

  return (
    <ol className={styles.list} aria-label={label}>
      {steps.map((s, i) => (
        <li key={s.id} className={styles.step} data-state={s.state}>
          <div className={styles.marker} aria-hidden="true">
            <span className={styles.dot}>{s.state === 'done' ? '✓' : null}</span>
            {i < steps.length - 1 ? <span className={styles.rail} data-rail /> : null}
          </div>
          <div className={styles.text}>
            <div className={styles.title}>
              <time dateTime={s.at}>{s.time}</time> · {s.title}
            </div>
            <div className={styles.detail}>
              <span className={styles.state}>{words[s.state]}.</span>
              {s.detail ? ` ${s.detail}` : null}
            </div>
          </div>
        </li>
      ))}
    </ol>
  );
}
