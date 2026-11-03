import { acceptsLine, doesNotAcceptLine } from '@/lib/criteria/model';
import type { CriteriaValues } from '@/lib/criteria/types';
import styles from './CriteriaPreview.module.css';

// What advisors will see if the change goes live, and what changed (W30, boards/lead/OwnerReview.dc.html state 4).
// The words are the same ones the advisor sees; the diff is computed by diffCriteria. An age change is shown as the
// field, what it was and what it is now; a change to a list is shown in the sentence the diff gives.

// diffCriteria says an age change as "Youngest age 18 to 16" or "Oldest age No limit to 80".
function splitAgeChange(change: string): { what: string; was: string; now: string } | null {
  const match = /^(Youngest age|Oldest age) (.+) to (.+)$/.exec(change);
  return match === null ? null : { what: match[1] ?? change, was: match[2] ?? '', now: match[3] ?? '' };
}

export function CriteriaPreview({ serviceName, values, changes }: { serviceName: string; values: CriteriaValues; changes: string[] }) {
  return (
    <div className={styles.card}>
      <h1 className={styles.heading}>Preview</h1>
      <div className={styles.panels}>
        <section className={styles.seen} aria-labelledby="owner-preview-seen">
          <h2 id="owner-preview-seen" className={styles.kicker}>What advisors will see</h2>
          <p className={styles.name}>{serviceName}</p>
          <p className={styles.line}>
            <b>Accepts</b> {acceptsLine(values).replace(/^Accepts: /, '')}
          </p>
          <p className={styles.line}>
            <b>Does not accept</b> {doesNotAcceptLine(values).replace(/^Does not accept: /, '')}
          </p>
        </section>
        <section className={styles.changed} aria-labelledby="owner-preview-changed">
          <h2 id="owner-preview-changed" className={styles.kicker}>What changed</h2>
          {changes.length === 0 ? (
            <p className={styles.nothing}>Nothing changed.</p>
          ) : (
            <>
              <ul className={styles.changes}>
                {changes.map((change) => {
                  const age = splitAgeChange(change);
                  return age === null ? (
                    <li key={change} className={styles.sentence}>
                      {change}
                    </li>
                  ) : (
                    <li key={change}>
                      <div className={styles.what}>{age.what}</div>
                      <p className={styles.values}>
                        <span className={styles.sr}>Was </span>
                        <span>{age.was}</span> <span aria-hidden="true">→</span>
                        <span className={styles.sr}> now </span> <b>{age.now}</b>
                      </p>
                    </li>
                  );
                })}
              </ul>
              <p className={styles.count}>
                {changes.length === 1 ? '1 change.' : `${changes.length} changes.`} Everything else is as it is now.
              </p>
            </>
          )}
        </section>
      </div>
    </div>
  );
}
