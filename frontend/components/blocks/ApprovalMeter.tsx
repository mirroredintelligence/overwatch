import styles from './ApprovalMeter.module.css';

// "n of m approvals": one segment per approval needed (filled when given), the count in words, and, when the
// names are known, who approved and the places still open. Shape plus word, never colour alone: a given place has
// a tick and "Approved", an open one a "?" and "Not yet asked".

export type Approver = { name: string; /** "2 Nov, 21:02" */ when?: string };

function initials(name: string): string {
  const words = name.trim().split(/\s+/).filter(Boolean);
  if (words.length === 0) return '?';
  const first = words[0]![0]!;
  const last = words.length > 1 ? words[words.length - 1]![0]! : '';
  return (first + last).toUpperCase();
}

export function ApprovalMeter({ given, needed, approvers }: { given: number; needed: number; approvers?: readonly Approver[] }) {
  const done = Math.min(Math.max(given, 0), needed);
  return (
    <div className={styles.meter}>
      <div className={styles.bar} role="img" aria-label={`${done} of ${needed} approvals`}>
        {Array.from({ length: needed }, (_, i) => (
          <span key={i} className={styles.segment} data-segment={i < done ? 'given' : 'open'} />
        ))}
      </div>
      <p className={styles.words}>
        <b>
          {done} of {needed} approvals given.
        </b>
      </p>
      {approvers ? (
        <ol className={styles.list} aria-label="Approvals">
          {approvers.slice(0, needed).map((a) => (
            <li key={a.name} className={styles.item}>
              <span className={styles.avatar} aria-hidden="true">
                {initials(a.name)}
              </span>
              <span className={styles.who}>
                <b>{a.name}</b>
                <span className={styles.when}>{a.when ? `Approved ${a.when}` : 'Approved'}</span>
              </span>
            </li>
          ))}
          {Array.from({ length: Math.max(needed - approvers.length, 0) }, (_, i) => (
            <li key={`open-${i}`} className={styles.item}>
              <span className={`${styles.avatar} ${styles.avatarOpen}`} aria-hidden="true">
                ?
              </span>
              <span className={styles.who}>
                <b>One more person</b>
                <span className={styles.when}>Not yet asked</span>
              </span>
            </li>
          ))}
        </ol>
      ) : null}
    </div>
  );
}
