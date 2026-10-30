import type { Metadata } from 'next';
import { AuditReplay } from '@/components/lead/AuditReplay';
import styles from '@/components/lead/Lead.module.css';
import { SERVICE_ID } from '@/lib/lead/routeParams';

// What the advisor saw for one reference (W47). At /lead/audit/<ref>. A reference with characters that cannot
// be one is the same "No record" as an unknown one, and is not looked up.

export const metadata: Metadata = {
  title: 'Audit replay - DIUCS capacity',
  robots: { index: false },
};

export default async function AuditReferencePage({ params }: { params: Promise<{ ref: string }> }) {
  const { ref } = await params;
  if (!SERVICE_ID.test(ref)) {
    return (
      <main className={styles.page}>
        <p role="alert" className={styles.fieldError}>
          No record for that reference.
        </p>
      </main>
    );
  }
  return <AuditReplay reference={ref} />;
}
