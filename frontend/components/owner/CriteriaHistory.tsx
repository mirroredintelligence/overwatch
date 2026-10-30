'use client';

import { useRouter } from 'next/navigation';
import { Banner } from '@/components/ui/Banner';
import { Button } from '@/components/ui/Button';
import { parseHistory } from '@/lib/criteria/history';
import { useRead } from '@/lib/bff/useRead';
import type { HistoryVersion } from '@/lib/criteria/types';
import styles from '@/components/lead/lead.module.css';

// The version history (W31, ui-screens CriteriaOwner screen 9). Every version is in the audit record.
// The back end gives each version's status and review date, not who made it: the page shows no role.

const STATUS_WORD: Record<HistoryVersion['status'], string> = {
  waiting: 'Waiting',
  current: 'Current',
  replaced: '',
  retired: 'Retired',
};

export function CriteriaHistory({ serviceId }: { serviceId: string }) {
  const router = useRouter();
  const read = useRead(`/api/bff/criteria/${encodeURIComponent(serviceId)}/history`, parseHistory);
  if (read.status === 'failed') return <main className={styles.page}><Banner tone="warning" title="The history could not be loaded. Try again shortly." /></main>;
  if (read.status === 'loading') return <main className={styles.page}><p>Loading…</p></main>;

  const versions = read.data.versions;
  const newest = versions.find((version) => version.status === 'current') ?? versions[0];
  return (
    <main className={styles.page}>
      <h1 className={styles.heading}>History</h1>
      <ul className={styles.list}>
        {versions.map((version) => (
          <li key={version.version} className={styles.meta}>
            <span>{`Version ${version.version}`}</span>
            <span>{version.version === 1 ? 'At registration' : STATUS_WORD[version.status]}</span>
          </li>
        ))}
      </ul>
      <p className={styles.hint}>Every version stays in the audit record.</p>
      {newest !== undefined ? (
        <div className={styles.actions}>
          <Button
            variant="secondary"
            onClick={() => router.push(`/criteria/${encodeURIComponent(serviceId)}?step=edit`)}
            dataEl="OWN-HISTORY-NEWDRAFT-BTN"
          >
            {`Start a new draft from version ${newest.version}`}
          </Button>
        </div>
      ) : null}
    </main>
  );
}
