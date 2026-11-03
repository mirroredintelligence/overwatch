import styles from './DiffPair.module.css';

// "Was" and "Now" as two sets of chips with an arrow between. A chip that is in Now and was not in Was is an
// addition: marked with "+" and, for a screen reader, the word "Added".

function Side({ label, items, was }: { label: 'Was' | 'Now'; items: readonly string[]; was?: readonly string[] }) {
  return (
    <div className={styles.side} role="group" aria-label={label}>
      <div className={styles.label} aria-hidden="true">
        {label}
      </div>
      {items.length === 0 ? (
        <span className={styles.none}>none</span>
      ) : (
        <ul className={styles.chips}>
          {items.map((item) => {
            const added = was !== undefined && !was.includes(item);
            return (
              <li key={item} className={styles.chip} data-added={added}>
                {added ? <span aria-hidden="true">+ </span> : null}
                {item}
                {added ? <span className={styles.sr}> Added</span> : null}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

export function DiffPair({ was, now }: { was: readonly string[]; now: readonly string[] }) {
  return (
    <div className={styles.pair}>
      <Side label="Was" items={was} />
      <div className={styles.arrow} aria-hidden="true">
        →
      </div>
      <Side label="Now" items={now} was={was} />
    </div>
  );
}
