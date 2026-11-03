import type { Metadata } from 'next';
import { AuditSearch } from '@/components/lead/AuditSearch';
import styles from '@/components/lead/Audit.module.css';

// The audit search (W47). At /lead/audit.

export const metadata: Metadata = {
  title: 'Audit replay - Overwatch',
  robots: { index: false },
};

export default function AuditPage() {
  return (
    <main className={styles.page}>
      <h1 className={styles.title}>Audit replay</h1>
      <div className={styles.narrow}>
        <AuditSearch />
      </div>
    </main>
  );
}
