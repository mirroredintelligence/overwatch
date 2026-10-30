'use client';

import { useEffect, useState } from 'react';
import { Banner } from '@/components/ui/Banner';
import { Button } from '@/components/ui/Button';
import { bffGet } from '@/lib/bff/client';
import {
  parseQueue,
  queueStateLabel,
  queueTabLabel,
  QUEUE_TABS,
  submittedText,
} from '@/lib/registration/model';
import type { QueueResponse, QueueTab } from '@/lib/registration/types';
import styles from './lead.module.css';

// The registrations queue (W28, ui-screens ApprovalWeb1 screen 2). Each tab asks the back end for
// its own items; the counts on every tab come from the same answer.

const PANEL_ID = 'registrations-panel';

export function RegistrationQueue() {
  const [tab, setTab] = useState<QueueTab>('waiting');
  const [data, setData] = useState<QueueResponse | null>(null);
  const [failed, setFailed] = useState(false);

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
  }, [tab]);

  return (
    <main className={styles.page}>
      <h1 className={styles.heading}>Registrations</h1>

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
        {failed ? <Banner tone="warning" title="The registrations could not be loaded. Try again shortly." /> : null}
        {data !== null && data.items.length === 0 ? <p>Nothing here.</p> : null}
        {data !== null && data.items.length > 0 ? (
          <ul className={styles.list}>
            {data.items.map((item) => (
              <li key={item.id} className={styles.card}>
                <p className={styles.name}>{item.serviceName}</p>
                <p className={styles.meta}>
                  <span className={styles.tag}>{queueStateLabel(item.state)}</span>
                </p>
                <p className={styles.meta}>{submittedText(item)}</p>
                <div>
                  <Button variant="secondary" href={`/lead/registrations/${encodeURIComponent(item.id)}`} dataEl="LEAD-REG-REVIEW-BTN">
                    Review
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        ) : null}
      </div>
    </main>
  );
}
