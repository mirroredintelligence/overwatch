'use client';

import { Banner } from '@/components/ui/Banner';
import { Button } from '@/components/ui/Button';
import { StatusTag } from '@/components/ui/StatusTag';
import { acceptsLine, doesNotAcceptLine, parseCriteriaOverview, shortDate, valuesOf } from '@/lib/criteria/model';
import type { CriteriaOverview as Overview, CriteriaStep } from '@/lib/criteria/types';
import { useRead } from '@/lib/bff/useRead';
import styles from '@/components/lead/lead-forms.module.css';
import panels from './CriteriaPanels.module.css';
import { OverdueNotice } from './OverdueNotice';

// The owner's overview of one service's criteria (W30, ui-screens CriteriaOwner screen 2, and the board's state 1
// Review). Advisors rely on these words, so the page says which version they see and that a new one is waiting.

// The review-due notice shows from this many days before the review date (the board's "due in 7 days").
const DUE_SOON_DAYS = 30;
const DAY_MS = 86_400_000;

/** Whole days from today to a YYYY-MM-DD review date, when that is within the due-soon window; null otherwise. */
function dueSoonDays(reviewBy: string): number | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(reviewBy);
  if (match === null) return null;
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const due = new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
  const days = Math.round((due.getTime() - today.getTime()) / DAY_MS);
  return days >= 0 && days <= DUE_SOON_DAYS ? days : null;
}

function dueWords(days: number): string {
  if (days === 0) return 'Criteria review due today';
  return `Criteria review due in ${days} ${days === 1 ? 'day' : 'days'}`;
}

export function CriteriaOverview({ serviceId, onNext }: { serviceId: string; onNext?: (step: CriteriaStep) => void }) {
  const read = useRead<Overview>(`/api/bff/criteria/${encodeURIComponent(serviceId)}`, parseCriteriaOverview);
  if (read.status === 'failed') return <main className={styles.page}><Banner tone="warning" title="These criteria could not be loaded. Try again shortly." /></main>;
  if (read.status === 'loading') return <main className={styles.page}><p>Loading…</p></main>;

  const { serviceName, current, draft, overdueSince, shiftLead } = read.data;
  const values = valuesOf(current);
  const dueIn = overdueSince === undefined ? dueSoonDays(current.reviewBy) : null;
  return (
    <main className={styles.page}>
      <div className={panels.card}>
        <h1 className={panels.title}>{serviceName} criteria</h1>
        {dueIn !== null ? (
          <section className={panels.due} aria-label="Review due">
            <StatusTag variant="due">{dueWords(dueIn)}</StatusTag>
            <p>{`Due ${shortDate(current.reviewBy)}. Confirm or update in about two minutes. If they are out of date, advisors see a flag on your service.`}</p>
          </section>
        ) : null}
        {overdueSince !== undefined ? (
          <OverdueNotice
            serviceName={serviceName}
            overdueSince={overdueSince}
            shiftLead={shiftLead}
            onReview={() => onNext?.('confirm')}
          />
        ) : null}
        <p className={panels.lede}>Advisors rely on these. They are the rules that decide whether a patient is offered to your service.</p>
        <p className={panels.meta}>{`Version ${current.version} · review by ${shortDate(current.reviewBy)}`}</p>
        <p className={panels.lede}>{acceptsLine(values)}</p>
        <p className={panels.lede}>{doesNotAcceptLine(values)}</p>
        {draft !== undefined ? (
          <p className={panels.meta}>{`Version ${draft.version} is waiting for approval. Advisors still see version ${current.version}.`}</p>
        ) : null}
        <div className={panels.actions}>
          <Button variant="primary" onClick={() => onNext?.('confirm')} dataEl="OWN-CRIT-STILLRIGHT-BTN">
            Still right
          </Button>
          <Button variant="secondary" onClick={() => onNext?.('edit')} dataEl="OWN-CRIT-CHANGE-BTN">
            Change them
          </Button>
          <div className={panels.end}>
            <Button variant="neutral" href={`/criteria/${encodeURIComponent(serviceId)}/history`} dataEl="OWN-CRIT-HISTORY-LINK">
              See the history
            </Button>
          </div>
        </div>
      </div>
    </main>
  );
}
