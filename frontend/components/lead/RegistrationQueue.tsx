'use client';

import { useEffect, useState } from 'react';
import { Button } from '@/components/ui/Button';
import { Loading, SkeletonRows } from '@/components/ui/Skeleton';
import { StatusTag, type StatusTagVariant } from '@/components/ui/StatusTag';
import { bffGet } from '@/lib/bff/client';
import {
  parseQueue,
  queueStateLabel,
  queueTabLabel,
  QUEUE_TABS,
  submittedText,
} from '@/lib/registration/model';
import type { QueueResponse, QueueTab } from '@/lib/registration/types';
import styles from './registration/RegistrationStage.module.css';

// The registrations queue (W28, ui-screens ApprovalWeb1 screen 2; board Rev1, phone board RvP1). Each tab asks
// the back end for its own items; the counts on every tab come from the same answer. The page around it
// (RegistrationStage) owns the heading and the landmark, and narrows this column when a registration opens.
// `selectedId` marks the open registration; `problems` holds the first automatic problem of a registration
// the shift lead has opened, copied onto its card.

const PANEL_ID = 'registrations-panel';

const STATE_VARIANT: Readonly<Record<string, StatusTagVariant>> = {
  submitted: 'waiting',
  'in-review': 'waiting',
  'needs-changes': 'waiting',
  approved: 'done',
  live: 'live',
  'not-approved': 'closed',
};

export function RegistrationQueue({
  selectedId,
  problems,
}: {
  selectedId?: string;
  problems?: Readonly<Record<string, string>>;
}) {
  const [tab, setTab] = useState<QueueTab>('waiting');
  const [data, setData] = useState<QueueResponse | null>(null);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let current = true;
    void (async () => {
      const result = await bffGet(`/api/bff/registrations?tab=${tab}`, parseQueue);
      if (!current) return;
      if (result.ok) {
        setData(result.data);
        setFailed(false);
      } else {
        setFailed(true);
      }
    })();
    return () => {
      current = false;
    };
  }, [tab, attempt]);

  return (
    <section aria-label="Queue" className={styles.queue}>
      <div className={styles.tabs} role="tablist" aria-label="Registrations">
        {QUEUE_TABS.map((option) => (
          <button
            key={option}
            type="button"
            role="tab"
            id={`tab-${option}`}
            aria-selected={option === tab}
            aria-controls={PANEL_ID}
            className={styles.tab}
            data-el={`LEAD-REG-TAB-${option.toUpperCase()}`}
            onClick={() => setTab(option)}
          >
            {queueTabLabel(option, data?.counts ?? null)}
          </button>
        ))}
      </div>

      <div role="tabpanel" id={PANEL_ID} aria-labelledby={`tab-${tab}`}>
        {failed ? (
          <div className={styles.error}>
            <h2 className={styles.stateTitle}>▲ We could not load the registrations</h2>
            <p className={styles.stateText}>
              Nothing has been lost. Check your connection and try again. If it keeps happening, tell the Overwatch team.
            </p>
            <button type="button" className={styles.again} onClick={() => setAttempt((n) => n + 1)}>
              Try again
            </button>
          </div>
        ) : null}
        {!failed && data === null ? (
          <Loading label="Loading the registrations.">
            <SkeletonRows count={2} />
          </Loading>
        ) : null}
        {!failed && data !== null && data.items.length === 0 ? (
          tab === 'waiting' ? (
            <div className={styles.empty}>
              <h2 className={styles.stateTitle}>Nothing to review</h2>
              <p className={styles.stateText}>
                New registrations appear here as soon as a service submits one. You will see a number on Review in the menu.
              </p>
              <Button variant="secondary" href="/lead/scope">
                Invite a service
              </Button>
            </div>
          ) : (
            <p className={styles.stateText}>Nothing here.</p>
          )
        ) : null}
        {!failed && data !== null && data.items.length > 0 ? (
          <ul className={styles.cards} aria-label="Registrations to review">
            {data.items.map((item) => {
              const problem = problems?.[item.id];
              const open = item.id === selectedId;
              return (
                <li key={item.id} className={styles.qcard} aria-current={open ? 'true' : undefined} data-open={open}>
                  <div className={styles.cardHead}>
                    <div className={styles.cardTitle}>
                      <p className={styles.name}>{item.serviceName}</p>
                      <p className={styles.meta}>{submittedText(item)}</p>
                    </div>
                    <StatusTag variant={STATE_VARIANT[item.state] ?? 'todo'}>{queueStateLabel(item.state)}</StatusTag>
                  </div>
                  {problem !== undefined ? (
                    <p className={styles.problemLine}>
                      <span aria-hidden="true">▲ </span>
                      <span className={styles.srOnly}>Needs attention:</span>
                      {problem}
                    </p>
                  ) : null}
                  <div>
                    <Button
                      variant={open ? 'primary' : 'secondary'}
                      href={`/lead/registrations/${encodeURIComponent(item.id)}`}
                      dataEl="LEAD-REG-REVIEW-BTN"
                    >
                      Review
                    </Button>
                  </div>
                </li>
              );
            })}
          </ul>
        ) : null}
      </div>
    </section>
  );
}
