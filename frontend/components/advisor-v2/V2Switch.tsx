import Link from 'next/link';
import styles from './V2.module.css';

// The top-level switch of Advisor v2 (DEC-1366): Capacity and Find a Service. Two links, not tabs that hide a page,
// so each view has its own address and the back button works. The current one is marked with aria-current and the
// word is the same either way: nothing here depends on colour.

export type V2Mode = 'capacity' | 'find';

export function V2Switch({ current }: { current: V2Mode }) {
  return (
    <nav aria-label="Advisor view" className={styles.switch}>
      <Link className={styles.switchLink} href="/advisor/v2?mode=capacity" aria-current={current === 'capacity' ? 'page' : undefined}>
        Capacity
      </Link>
      <Link className={styles.switchLink} href="/advisor/v2?mode=find" aria-current={current === 'find' ? 'page' : undefined}>
        Find a Service
      </Link>
    </nav>
  );
}
