import styles from './CriteriaSummary.module.css';

// The four criteria a patient search is built on, shown as one summary. A set value gets a filled dot and an unset one
// an open circle; both are decorative, so the words carry the meaning for a screen reader.

export type CriteriaSummaryProps = { age: string | null; district: string | null; needs: readonly string[]; urgency: string | null };

function Value({ value }: { value: string | null }) {
  if (value === null || value === '') {
    return (
      <>
        <span aria-hidden="true" className={styles.unset}>
          {'○'}
        </span>{' '}
        Not set
      </>
    );
  }
  return (
    <>
      <span aria-hidden="true" className={styles.set}>
        {'●'}
      </span>{' '}
      {value}
    </>
  );
}

export function CriteriaSummary({ age, district, needs, urgency }: CriteriaSummaryProps) {
  const need = needs.length > 0 ? needs.join(', ') : null;
  return (
    <section aria-label="Criteria" className={styles.root}>
      <dl className={styles.grid}>
        <div className={styles.item}>
          <dt className={styles.term}>Age</dt>
          <dd className={styles.value}>
            <Value value={age} />
          </dd>
        </div>
        <div className={styles.item}>
          <dt className={styles.term}>Postcode</dt>
          <dd className={styles.value}>
            <Value value={district} />
          </dd>
        </div>
        <div className={styles.item}>
          <dt className={styles.term}>Need</dt>
          <dd className={styles.value}>
            <Value value={need} />
          </dd>
        </div>
        <div className={styles.item}>
          <dt className={styles.term}>Timeframe</dt>
          <dd className={styles.value}>
            <Value value={urgency} />
          </dd>
        </div>
      </dl>
    </section>
  );
}
