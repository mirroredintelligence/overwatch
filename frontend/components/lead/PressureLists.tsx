import { StatusBadge } from '@/components/ui/StatusBadge';
import type { PressureItem, UnderutilisedItem } from '@/lib/lead/types';
import styles from './PressureLists.module.css';

// Where the system is tight and where it has room (DEC-1343). Under pressure shows the services that are over
// capacity, not accepting or limited, most pressed first; a service whose figure is old shows "Unknown" and the
// words to confirm first, never a percentage. Underutilised lists only services with a fresh figure that are at
// most 60% used with at least 25% free: a stale or unknown figure is never listed as spare capacity, and the list
// is for the lead to see, not a recommendation of where to send a patient. Each list shows its first few.

const SHOWN = 5;

function percentText(percent: number | null): string {
  return percent === null ? 'Unknown' : `${percent}% used`;
}

export function UnderPressureList({ items }: { items: PressureItem[] }) {
  const shown = items.slice(0, SHOWN);
  return (
    <section className={styles.card} aria-labelledby="lead-pressure-heading" data-el="LEAD-PRESSURE">
      <h2 id="lead-pressure-heading" className={styles.heading}>
        Under pressure
      </h2>
      {items.length === 0 ? (
        <p className={styles.none}>No service is under pressure.</p>
      ) : (
        <>
          <ul className={styles.rows}>
            {shown.map((item) => (
              <li key={item.serviceId} className={styles.row}>
                <span className={styles.name}>{item.name}</span>
                <StatusBadge status={item.status} />
                <span className={styles.detail}>{`${item.reason} · ${percentText(item.usedPercent)}`}</span>
              </li>
            ))}
          </ul>
          {items.length > shown.length ? <p className={styles.note}>{`and ${items.length - shown.length} more`}</p> : null}
        </>
      )}
    </section>
  );
}

export function UnderutilisedList({ items }: { items: UnderutilisedItem[] }) {
  const shown = items.slice(0, SHOWN);
  return (
    <section className={styles.card} aria-labelledby="lead-underused-heading" data-el="LEAD-UNDERUSED">
      <h2 id="lead-underused-heading" className={styles.heading}>
        Underutilised
      </h2>
      {items.length === 0 ? (
        <p className={styles.none}>No service has spare room on a current figure.</p>
      ) : (
        <>
          <p className={styles.note}>Current figures only. This is not a recommendation of where to send a patient.</p>
          <ul className={styles.rows}>
            {shown.map((item) => (
              <li key={item.serviceId} className={styles.row}>
                <span className={styles.name}>{item.name}</span>
                <span className={styles.detail}>{`${item.usedPercent}% used · ${item.spare} ${item.unitLabel}`}</span>
              </li>
            ))}
          </ul>
          {items.length > shown.length ? <p className={styles.note}>{`and ${items.length - shown.length} more`}</p> : null}
        </>
      )}
    </section>
  );
}
