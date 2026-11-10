import { BROWSE_STATUSES } from '@/lib/advisor/servicesBrowse';
import type { StatusTally } from '@/lib/analytics/groups';
import { ShapeIcon, STATUS_LABELS, STATUS_SHAPES } from '@/components/ui/StatusBadge';
import styles from './Analytics.module.css';

// A stacked bar of a group's services by status (DEC-1368). The bar is a picture only (aria-hidden): the same
// figures are written under it as a count and a word beside a shape, so no meaning rests on colour. The segments
// follow the board's order of statuses and are not ranked.

export function StatusBar({ counts }: { counts: StatusTally }) {
  const total = BROWSE_STATUSES.reduce((sum, status) => sum + counts[status as keyof StatusTally], 0);
  return (
    <>
      <div className={styles.bar} aria-hidden="true">
        {BROWSE_STATUSES.map((status) => {
          const n = counts[status as keyof StatusTally];
          return n === 0 ? null : <span key={status} className={styles.segment} data-status={status} style={{ flexGrow: n }} />;
        })}
        {total === 0 ? <span className={styles.segment} data-status="none" style={{ flexGrow: 1 }} /> : null}
      </div>
      <ul className={styles.legend}>
        {BROWSE_STATUSES.map((status) => {
          const n = counts[status as keyof StatusTally];
          return n === 0 ? null : (
            <li key={status} className={styles.legendItem}>
              <span className={styles.shape}>
                <ShapeIcon shape={STATUS_SHAPES[status]} />
              </span>
              {`${n} ${STATUS_LABELS[status]}`}
            </li>
          );
        })}
        {total === 0 ? <li className={styles.legendItem}>No services</li> : null}
      </ul>
    </>
  );
}
