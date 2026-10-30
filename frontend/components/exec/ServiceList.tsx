import Link from 'next/link';
import { StatusBadge, type StatusCode } from '@/components/ui/StatusBadge';
import type { BoardEntry } from '@/lib/board/types';
import styles from './Exec.module.css';

// Every service on the board, with its status word (W40, "See all services"). The link goes to the
// service's own page; the list holds no figure beyond the board's.

export function ServiceList({ entries }: { entries: BoardEntry[] }) {
  return (
    <ul className={styles.attention} aria-label="All services">
      {entries.map((entry) => (
        <li key={entry.serviceId}>
          <Link href={`/planning/services/${encodeURIComponent(entry.serviceId)}`} className={styles.serviceLink}>
            <span className={styles.serviceName}>{entry.name}</span>
            <StatusBadge status={entry.status as StatusCode} />
          </Link>
        </li>
      ))}
    </ul>
  );
}
