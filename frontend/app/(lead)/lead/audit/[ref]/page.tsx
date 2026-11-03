import type { Metadata } from 'next';
import { AuditReplay } from '@/components/lead/AuditReplay';
import { AuditSearch } from '@/components/lead/AuditSearch';
import styles from '@/components/lead/Audit.module.css';
import { SERVICE_ID } from '@/lib/lead/routeParams';

// What the advisor saw for one reference (W47). At /lead/audit/<ref>. The search sits beside the replay on wide
// screens and above it on phones. A reference with characters that cannot be one is the same "No record" as an
// unknown one, and is not looked up.

export const metadata: Metadata = {
  title: 'Audit replay - Overwatch',
  robots: { index: false },
};

export default async function AuditReferencePage({ params }: { params: Promise<{ ref: string }> }) {
  const { ref } = await params;
  if (!SERVICE_ID.test(ref)) {
    return (
      <main className={styles.page}>
        <div className={styles.layout}>
          <aside className={styles.side}>
            <AuditSearch />
          </aside>
          <section className={styles.card} aria-labelledby="replay-title">
            <h1 id="replay-title" className={styles.title}>
              What the advisor saw
            </h1>
            <p role="alert" className={styles.fieldError}>
              No record for that reference.
            </p>
          </section>
        </div>
      </main>
    );
  }
  return (
    <main className={styles.page}>
      <div className={styles.layout}>
        <aside className={styles.side}>
          <AuditSearch />
        </aside>
        <AuditReplay reference={ref} />
      </div>
    </main>
  );
}
