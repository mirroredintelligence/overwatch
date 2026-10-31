import type { Metadata } from 'next';
import { CoverageByTime } from '@/components/areas/CoverageByTime';
import styles from '@/components/console/Console.module.css';
import { getSession } from '@/lib/auth/session';
import { PLANNING_ROLES } from '@/lib/planning/backend';

export const metadata: Metadata = {
  title: 'Coverage by time of day · Overwatch',
};

export const dynamic = 'force-dynamic';

// Where coverage runs out (RadarWeb 4), at /planning/coverage. For the lead and the executive, like the
// planning view next to it.
export default async function CoveragePage() {
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
      <CoverageByTime />
    </main>
  );
}
