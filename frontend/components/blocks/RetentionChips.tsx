import styles from './RetentionChips.module.css';

// The retention summary (admin Data retention, A5): one chip per kind of data, its rule written out
// ("Bookings: 2 years, then deleted"). A kept rule has the primary frame; the word "kept" is in its text,
// so the frame is not the only signal.

export type RetentionChip = { id: string; text: string; kept?: boolean };

export function RetentionChips({ label, items }: { label: string; items: readonly RetentionChip[] }) {
  if (items.length === 0) return null;
  return (
    <ul className={styles.list} aria-label={label}>
      {items.map((item) => (
        <li key={item.id} className={styles.chip} data-kept={item.kept ? 'true' : undefined}>
          {item.text}
        </li>
      ))}
    </ul>
  );
}
