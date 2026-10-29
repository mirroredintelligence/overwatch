import { ShapeIcon, STATUS_SHAPES, type StatusCode } from '@/components/ui/StatusBadge';
import styles from './Legend.module.css';

// The key under the board (ui-screens.md, artboard "Main"). Each meaning has the
// same shape as its status badge, so it is never colour alone.
const ITEMS: { status: StatusCode; text: string }[] = [
  { status: 'accepting', text: 'Accepting' },
  { status: 'limited', text: 'Limited: phone to confirm' },
  { status: 'not-accepting', text: 'Not accepting' },
  { status: 'over-capacity', text: 'Over capacity' },
  { status: 'not-updated', text: 'Not updated: treat as unknown, phone' },
];

export function Legend() {
  return (
    <ul className={styles.legend} aria-label="Status key">
      {ITEMS.map(({ status, text }) => (
        <li key={status} className={styles.item}>
          <span className={`${styles.swatch} ${styles[status]}`} data-shape={STATUS_SHAPES[status]} aria-hidden="true">
            <ShapeIcon shape={STATUS_SHAPES[status]} />
          </span>
          {text}
        </li>
      ))}
    </ul>
  );
}
