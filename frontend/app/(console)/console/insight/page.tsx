import type { Metadata } from 'next';
import { InsightTabs } from '@/components/console/insight/InsightTabs';
import styles from '@/components/console/Console.module.css';
import { getSession } from '@/lib/auth/session';
import { CONSOLE_ROLES } from '@/lib/console/backend';
import { TABS, type InsightTab } from '@/lib/console/insight';

export const metadata: Metadata = {
  title: 'DIUCS console: insight',
};

export const dynamic = 'force-dynamic';

export default async function InsightPage({ searchParams }: { searchParams: Promise<{ tab?: string }> }) {
  const session = await getSession();
  if (!session || !CONSOLE_ROLES.includes(session.role)) {
    return (
      <main className={styles.page}>
        <p role="alert" className={styles.alert}>You do not have access to the console.</p>
      </main>
    );
  }
  const requested = (await searchParams).tab ?? '';
  const initial: InsightTab = (TABS as readonly string[]).includes(requested) ? (requested as InsightTab) : 'funnels';
  return (
    <main className={styles.page}>
      <h1 className={styles.heading}>Insight</h1>
      <p className={styles.help}>Aggregates only. No person is shown.</p>
      <InsightTabs initialTab={initial} />
    </main>
  );
}
