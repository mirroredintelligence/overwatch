import type { Metadata } from 'next';
import { PlanningView } from '@/components/planning/PlanningView';
import layout from '@/components/planning/Planning.module.css';
import { getSession } from '@/lib/auth/session';
import { PLANNING_ROLES } from '@/lib/planning/backend';

export const metadata: Metadata = {
  title: 'Overwatch: planning',
};

export const dynamic = 'force-dynamic';

export default async function PlanningPage() {
  const session = await getSession();
  if (!session || !PLANNING_ROLES.includes(session.role)) {
    return (
      <main className={layout.page}>
        <p role="alert" className={layout.alert}>You do not have access to planning.</p>
      </main>
    );
  }
  return (
    <main className={layout.page}>
      <PlanningView />
    </main>
  );
}
