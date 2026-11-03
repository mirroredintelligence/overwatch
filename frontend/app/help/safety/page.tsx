import type { Metadata } from 'next';
import { SafetyConcernForm } from '@/components/help/SafetyConcernForm';
import styles from '@/components/help/Help.module.css';
import { copy } from '@/lib/copy';
import { currentProfile } from '@/lib/tenant/profile';

export const metadata: Metadata = { title: 'Report a safety concern - Overwatch' };
export const dynamic = 'force-dynamic';

// The tenant's own coordination team and number, when it has set them: "Phone <team> on <number>." Nothing
// is made up for a tenant that has not (H-T15).
export default async function SafetyConcernPage() {
  const profile = await currentProfile().catch(() => null);
  return (
    <main className={styles.card} data-help-form>
      <h1 className={styles.cardTitle}>Report a safety concern</h1>
      <SafetyConcernForm coordinationLine={copy.phoneTheCoordinationTeam(profile)} />
    </main>
  );
}
