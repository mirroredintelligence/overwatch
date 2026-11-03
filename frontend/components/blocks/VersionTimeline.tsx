import type { ReactNode } from 'react';
import styles from './VersionTimeline.module.css';

// The versions of one thing, newest first, down a rail (criteria history). Each state is a shape AND a word:
// waiting = dashed ring + dashed tag, live = filled dot + dot in the tag, earlier = pale dot. The live version
// is the current one (aria-current) and carries its facts open; the others are one line.

export type VersionState = 'waiting' | 'live' | 'earlier';

export type VersionEntry = {
  id: string;
  title: string;
  state: VersionState;
  /** The state in words: "Live now", "Waiting for approval", "At registration". */
  stateLabel: string;
  detail?: ReactNode;
  facts?: readonly { label: string; value: ReactNode }[];
};

export function VersionTimeline({ label, versions }: { label: string; versions: readonly VersionEntry[] }) {
  return (
    <ol className={styles.list} aria-label={label}>
      {versions.map((v, i) => (
        <li key={v.id} className={styles.version} data-state={v.state} aria-current={v.state === 'live' ? 'true' : undefined}>
          <div className={styles.rail} aria-hidden="true">
            <span className={styles.point} />
            {i < versions.length - 1 ? <span className={styles.line} data-line /> : null}
          </div>
          <div className={styles.card}>
            <div className={styles.head}>
              <div className={styles.title}>{v.title}</div>
              <span className={styles.tag}>
                {v.state === 'live' ? <span className={styles.tagDot} aria-hidden="true" /> : null}
                {v.stateLabel}
              </span>
            </div>
            {v.detail ? <div className={styles.detail}>{v.detail}</div> : null}
            {v.facts !== undefined && v.facts.length > 0 ? (
              <dl className={styles.facts}>
                {v.facts.map((f) => (
                  <div key={f.label}>
                    <dt className={styles.k}>{f.label}</dt>
                    <dd className={styles.fact}>{f.value}</dd>
                  </div>
                ))}
              </dl>
            ) : null}
          </div>
        </li>
      ))}
    </ol>
  );
}
