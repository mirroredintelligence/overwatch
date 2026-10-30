'use client';

import { useEffect, useState } from 'react';
import { Banner } from '@/components/ui/Banner';
import { Button } from '@/components/ui/Button';
import { bffGet } from '@/lib/bff/client';
import { parseOverview } from '@/lib/registration/model';
import type { CallBackState, CriteriaState, Overview, ScopeState } from '@/lib/registration/types';
import styles from './lead.module.css';

// One registration's review overview (W28, ui-screens ApprovalWeb1 screen 3). It shows what the
// system checked and what the reviewer still does. The checks themselves are on the step pages (W29).

const CALLBACK_TEXT: Record<CallBackState, string> = { 'not-done': 'Not done', done: 'Done' };
const SCOPE_TEXT: Record<ScopeState, string> = { 'not-done': 'Not done', done: 'Done' };
const CRITERIA_TEXT: Record<CriteriaState, string> = {
  'not-done': 'Not done',
  waiting: 'Waiting for the clinical lead',
  done: 'Done',
};

export function RegistrationOverview({ id }: { id: string }) {
  const [overview, setOverview] = useState<Overview | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let current = true;
    void (async () => {
      const result = await bffGet(`/api/bff/registrations/${encodeURIComponent(id)}`, parseOverview);
      if (!current) return;
      if (result.ok) {
        setOverview(result.data);
        setFailed(false);
      } else {
        setFailed(true);
      }
    })();
    return () => {
      current = false;
    };
  }, [id]);

  if (failed) {
    return (
      <main className={styles.page}>
        <Banner tone="warning" title="This registration could not be loaded. Try again shortly." />
      </main>
    );
  }
  if (overview === null) {
    return (
      <main className={styles.page}>
        <p>Loading…</p>
      </main>
    );
  }

  const { manualChecks } = overview;
  const decideOpen = manualChecks.callback !== 'done' || manualChecks.scope !== 'done' || manualChecks.criteria !== 'done';

  return (
    <main className={styles.page}>
      <p className={styles.meta}>
        Registered by {overview.registeredBy.name}, {overview.registeredBy.role}
      </p>
      <h1 className={styles.heading}>{overview.serviceName}</h1>

      <h2 className={styles.section}>Checks the system did</h2>
      <ul className={styles.list}>
        {overview.automaticChecks.map((check) => (
          <li key={check.key} className={styles.meta}>
            <span>{check.label}</span> <span className={styles.tag}>{check.ok ? 'Passed' : 'Warning'}</span>
            {!check.ok && check.action !== undefined ? <p className={styles.hint}>{check.action}</p> : null}
          </li>
        ))}
      </ul>

      <h2 className={styles.section}>Checks you do</h2>
      <ol className={styles.steps}>
        <li>
          <span>Call back the service</span> <span>{CALLBACK_TEXT[manualChecks.callback]}</span>
        </li>
        <li>
          <span>Decide if it is in scope</span> <span>{SCOPE_TEXT[manualChecks.scope]}</span>
        </li>
        <li>
          <span>Criteria second approval</span> <span>{CRITERIA_TEXT[manualChecks.criteria]}</span>
        </li>
        <li>
          <span>Decide</span> <span>{decideOpen ? 'Opens when 1 to 3 are done' : 'Ready to decide'}</span>
        </li>
      </ol>

      <div className={styles.actions}>
        <Button variant="primary" href={`/lead/registrations/${encodeURIComponent(id)}?step=callback`} dataEl="LEAD-REG-START-CALLBACK-BTN">
          Start with the call-back
        </Button>
      </div>
    </main>
  );
}
