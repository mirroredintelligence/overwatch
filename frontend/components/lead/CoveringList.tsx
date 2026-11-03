import { Button } from '@/components/ui/Button';
import { clockTime } from '@/lib/lead/format';
import type { CoveringItem } from '@/lib/lead/types';
import styles from './CoveringList.module.css';

// Who the reports go to today (W17). Tenant-only: the covering numbers are the organisation's own. When no one is
// covering, it says so (the quiet board), never an empty list.

export function CoveringList({ items }: { items: CoveringItem[] }) {
  return (
    <section className={styles.card} aria-labelledby="lead-covering-heading" data-el="LEAD-COVERING">
      <h2 id="lead-covering-heading" className={styles.heading}>
        Covering today
      </h2>
      {items.length === 0 ? (
        <p className={styles.none}>No one is covering for anyone. Every service reports to its usual contact.</p>
      ) : (
        <>
          <p className={styles.note}>Reports go to a registered number. Change it for leave or cover.</p>
          <ul className={styles.rows}>
            {items.map((item) => (
              <li key={item.serviceId} className={styles.row}>
                <div className={styles.text}>
                  <span className={styles.name}>{item.name}</span>
                  <span className={styles.detail}>
                    {`ending ${item.numberEnding} · ${
                      item.until === null ? 'usual contact' : `cover until ${clockTime(item.until)}`
                    }`}
                  </span>
                </div>
                <Button
                  variant="secondary"
                  href={`/lead/reporters/number?service=${encodeURIComponent(item.serviceId)}`}
                  ariaLabel={`Change number for ${item.name}`}
                  dataEl="LEAD-COVERING-NUMBER-LINK"
                >
                  Change
                </Button>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
