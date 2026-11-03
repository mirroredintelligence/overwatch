'use client';

import { useRouter } from 'next/navigation';
import { VersionTimeline, type VersionEntry, type VersionState } from '@/components/blocks/VersionTimeline';
import { PageHeader } from '@/components/shell/PageHeader';
import { Banner } from '@/components/ui/Banner';
import { Button } from '@/components/ui/Button';
import { Loading, SkeletonRows } from '@/components/ui/Skeleton';
import { shortDate } from '@/lib/criteria/model';
import { parseHistory } from '@/lib/criteria/history';
import { useRead } from '@/lib/bff/useRead';
import type { HistoryVersion } from '@/lib/criteria/types';
import styles from './CriteriaHistory.module.css';

// The version history (W31, ui-screens CriteriaOwner screen 9). Every version is in the audit record.
// The back end gives each version's status and review date, not who made it or what changed: the timeline
// shows version, state and review-by only, and the live version's facts are not shown until the data has them.

const STATE_OF: Record<HistoryVersion['status'], VersionState> = {
  waiting: 'waiting',
  current: 'live',
  replaced: 'earlier',
  retired: 'earlier',
};

/** The timeline lines, newest first. An earlier version says which newer one replaced it (the nearest one not retired). */
function entriesOf(versions: readonly HistoryVersion[]): VersionEntry[] {
  return versions.map((version, index) => {
    const state = STATE_OF[version.status];
    const stateLabel =
      version.status === 'waiting'
        ? 'Waiting for approval'
        : version.status === 'current'
          ? 'Live now'
          : version.status === 'retired'
            ? 'Retired'
            : version.version === 1
              ? 'At registration'
              : 'Replaced';
    const replacedBy = versions.slice(0, index).reverse().find((newer) => newer.status !== 'retired');
    let detail: string | undefined;
    if (state === 'earlier') {
      detail = replacedBy !== undefined && version.status === 'replaced' ? `Replaced by version ${replacedBy.version}` : undefined;
    } else if (version.reviewBy !== '') {
      detail = `Review by ${shortDate(version.reviewBy)}`;
    }
    return { id: `v${version.version}`, title: `Version ${version.version}`, state, stateLabel, detail };
  });
}

export function CriteriaHistory({ serviceId }: { serviceId: string }) {
  const router = useRouter();
  const read = useRead(`/api/bff/criteria/${encodeURIComponent(serviceId)}/history`, parseHistory);

  if (read.status === 'loading') {
    return (
      <main className={styles.page}>
        <PageHeader title="History" />
        <Loading label="Loading the history.">
          <SkeletonRows count={3} />
        </Loading>
      </main>
    );
  }
  if (read.status === 'failed') {
    return (
      <main className={styles.page}>
        <PageHeader title="History" />
        <Banner tone="warning" title="The history could not be loaded. Try again shortly." />
      </main>
    );
  }

  const versions = read.data.versions;
  // The draft starts from the live version. A history with no live version offers no new draft.
  const live = versions.find((version) => version.status === 'current');
  return (
    <main className={styles.page}>
      <PageHeader title="History" />
      <div className={styles.layout}>
        <VersionTimeline label="Versions" versions={entriesOf(versions)} />
        <aside className={styles.side} aria-label="What you can do">
          {live !== undefined ? (
            <section className={styles.card} aria-labelledby="history-start">
              <h2 id="history-start" className={styles.k}>Start a change</h2>
              <p className={styles.lede}>You can start a new draft from the live version. It goes to a second person before advisors see it.</p>
              <div className={styles.draft}>
                <Button
                  variant="secondary"
                  onClick={() => router.push(`/criteria/${encodeURIComponent(serviceId)}?step=edit`)}
                  dataEl="OWN-HISTORY-NEWDRAFT-BTN"
                >
                  {`Start a new draft from version ${live.version}`}
                </Button>
              </div>
            </section>
          ) : null}
          <section className={`${styles.card} ${styles.record}`} aria-labelledby="history-record">
            <h2 id="history-record" className={`${styles.k} ${styles.recordK}`}>The record</h2>
            <p className={`${styles.lede} ${styles.recordLede}`}>
              Every version stays in the audit record, with who sent it and who approved it. Nothing is ever deleted.
            </p>
          </section>
        </aside>
      </div>
    </main>
  );
}
