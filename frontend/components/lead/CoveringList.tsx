import { Button } from '@/components/ui/Button';
import { clockTime } from '@/lib/lead/format';
import type { CoveringItem } from '@/lib/lead/types';
import styles from './Lead.module.css';

// Who the reports go to today (W17). Tenant-only: the covering numbers are the organisation's own.

export function CoveringList({ items }: { items: CoveringItem[] }) {
  return (
    <section className={styles.section} aria-labelledby="lead-covering-heading" data-el="LEAD-COVERING">
      <h2 id="lead-covering-heading" className={styles.sectionHeading}>
        Covering today
      </h2>
      <p className={styles.muted}>Reports go to a registered number. Change it for leave or cover.</p>
      <ul className={styles.rows}>
        {items.map((item) => (
          <li key={item.serviceId} className={styles.row}>
            <span>
              {`${item.name} · number ending ${item.numberEnding} · ${
                item.until === null ? 'usual contact' : `cover until ${clockTime(item.until)}`
              }`}
            </span>
            <Button
              variant="neutral"
              href={`/lead/reporters/number?service=${encodeURIComponent(item.serviceId)}`}
              dataEl="LEAD-COVERING-NUMBER-LINK"
            >
              Change number
            </Button>
          </li>
        ))}
      </ul>
    </section>
  );
}
