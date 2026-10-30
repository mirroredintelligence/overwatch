'use client';

import { Banner } from '@/components/ui/Banner';
import { Button } from '@/components/ui/Button';
import { acceptsLine, doesNotAcceptLine, parseCriteriaOverview, shortDate, valuesOf } from '@/lib/criteria/model';
import type { CriteriaOverview as Overview, CriteriaStep } from '@/lib/criteria/types';
import { useRead } from '@/lib/bff/useRead';
import styles from '@/components/lead/lead.module.css';

// The owner's overview of one service's criteria (W30, ui-screens CriteriaOwner screen 2). Advisors
// rely on these words, so the page says which version they see and that a new one is waiting.

export function CriteriaOverview({ serviceId, onNext }: { serviceId: string; onNext?: (step: CriteriaStep) => void }) {
  const read = useRead<Overview>(`/api/bff/criteria/${encodeURIComponent(serviceId)}`, parseCriteriaOverview);
  if (read.status === 'failed') return <main className={styles.page}><Banner tone="warning" title="These criteria could not be loaded. Try again shortly." /></main>;
  if (read.status === 'loading') return <main className={styles.page}><p>Loading…</p></main>;

  const { serviceName, current, draft } = read.data;
  const values = valuesOf(current);
  return (
    <main className={styles.page}>
      <h1 className={styles.heading}>{serviceName} criteria</h1>
      <p className={styles.meta}>{`Version ${current.version} · review by ${shortDate(current.reviewBy)}`}</p>
      <p className={styles.lede}>{acceptsLine(values)}</p>
      <p className={styles.lede}>{doesNotAcceptLine(values)}</p>
      <p className={styles.hint}>Advisors rely on these. If they are out of date, advisors see a flag on your service.</p>
      {draft !== undefined ? (
        <p className={styles.meta}>{`Version ${draft.version} is waiting for approval. Advisors still see version ${current.version}.`}</p>
      ) : null}
      <div className={styles.actions}>
        <Button variant="primary" onClick={() => onNext?.('confirm')} dataEl="OWN-CRIT-STILLRIGHT-BTN">
          Still right
        </Button>
        <Button variant="secondary" onClick={() => onNext?.('edit')} dataEl="OWN-CRIT-CHANGE-BTN">
          Change
        </Button>
      </div>
    </main>
  );
}
