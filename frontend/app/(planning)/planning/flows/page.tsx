import type { Metadata } from 'next';
import { PlanningView } from '@/components/planning/PlanningView';
import styles from '@/components/console/Console.module.css';
import { getSession } from '@/lib/auth/session';
import { PLANNING_ROLES } from '@/lib/planning/backend';

export const metadata: Metadata = {
  title: 'DIUCS capacity: planning',
};

export const dynamic = 'force-dynamic';

export default async function PlanningPage() {
  const session = await getSession();
  if (!session || !PLANNING_ROLES.includes(session.role)) {
    return (
      <main className={styles.page}>
        <p role="alert" className={styles.alert}>You do not have access to planning.</p>
      </main>
    );
  }
  return (
    <main className={styles.page}>
      <PlanningView />
    </main>
  );
}
