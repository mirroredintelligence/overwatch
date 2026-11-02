'use client';

import { useEffect, useRef, useState } from 'react';
import { useOperatorRead } from '@/lib/operator/browser';
import { deriveFunnel, PHASE_STATE_WORD, type Consent, type PhaseId } from '@/lib/operator/funnel';
import type { parseTenantDetail } from '@/lib/operator/views';
import { TENANT_STATUS_WORD } from '@/lib/operator/words';
import { LifecyclePanel, type Notice } from './TenantLifecycle';
import { PhasePanel, phaseTagClass } from './TenantPhases';
import styles from '@/components/admin/admin.module.css';
import ts from './Tenant.module.css';

// One partner organisation's page (TEN-083): a guided "Go live". A task list of five parts (each a link with its
// status in words and one line on where it stands) and, beside it (under it on a phone), only the selected part:
// by default the first part that is not completed. A completed part shows a short summary and a "Change" link.
// Every write is the operator's own. No secret is shown. The state is derived from the detail and the approval link
// the page already reads (`lib/operator/funnel.ts`); nothing new is written or stored for it.

type Detail = ReturnType<typeof parseTenantDetail>;

export function TenantDetail({ tenantId }: { tenantId: string }) {
  const { state, reload } = useOperatorRead<Detail>(`/api/bff/platform/tenants/${tenantId}`);
  const consentRead = useOperatorRead<Consent>(`/api/bff/platform/tenants/${tenantId}/admin-consent`);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [unrecorded, setUnrecorded] = useState(false);
  // The part the operator chose (null: the first that is not completed), and the completed part kept open.
  const [chosen, setChosen] = useState<PhaseId | null>(null);
  const [open, setOpen] = useState<PhaseId | null>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const [focusTick, setFocusTick] = useState(0);
  useEffect(() => {
    // Choosing a part moves focus to its heading, so a screen reader hears where it landed.
    if (focusTick > 0) headingRef.current?.focus();
  }, [focusTick]);

  if (state.status === 'loading') {
    return (
      <main className={styles.page}>
        <p className={styles.muted}>Loading the organisation.</p>
      </main>
    );
  }
  if (state.status === 'failed') {
    return (
      <main className={styles.page}>
        <p role="alert" className={styles.problem}>
          {state.http === 404 ? 'We could not find that organisation.' : 'We could not load the organisation.'}
        </p>
      </main>
    );
  }
  const detail = state.data;
  const funnel = deriveFunnel(detail, consentRead.state);
  const selectedId: PhaseId = chosen ?? (detail.tenant.status === 'provisioning' ? funnel.nextPhase : null) ?? 'golive';
  const selected = funnel.phases.find((p) => p.id === selectedId)!;
  const select = (id: PhaseId) => {
    setChosen(id);
    setOpen(null);
    setFocusTick((n) => n + 1);
  };
  const onChanged = () => {
    reload();
    consentRead.reload();
    // Stay where the work was done, so what was said stays on screen, even when the part has just been completed.
    setChosen(selectedId);
    setOpen(selectedId);
  };
  const completed = funnel.phases.filter((p) => p.done).length;

  return (
    <main className={ts.page}>
      <div className={ts.head}>
        <h1 className={styles.title}>{detail.tenant.displayName}</h1>
        <div className={ts.headRow}>
          <span className={detail.tenant.status === 'active' ? styles.tag : `${styles.tag} ${styles.tagDashed}`}>{TENANT_STATUS_WORD[detail.tenant.status] ?? detail.tenant.status}</span>
          {detail.tenant.status === 'provisioning' ? <span className={styles.muted}>{`${completed} of ${funnel.phases.length} parts completed`}</span> : null}
        </div>
      </div>

      {unrecorded ? (
        <p role="alert" className={styles.problem}>
          The step was done, but the platform record could not be written. Do not repeat it. Tell the person who looks after the platform record.
        </p>
      ) : null}
      {notice !== null ? (
        <p role={notice.ok ? 'status' : 'alert'} className={notice.ok ? styles.ok : styles.problem}>
          {notice.text}
        </p>
      ) : null}

      <div className={ts.layout}>
        <nav className={ts.tasks} aria-label="Go live tasks">
          <ol className={ts.taskList}>
            {funnel.phases.map((p) => (
              <li key={p.id} className={ts.task} data-state={p.state}>
                <a
                  className={ts.taskLink}
                  href={`#phase-${p.id}`}
                  aria-current={p.id === selectedId ? 'step' : undefined}
                  aria-describedby={`task-${p.id}-status task-${p.id}-summary`}
                  onClick={(event) => {
                    event.preventDefault();
                    select(p.id);
                  }}
                >
                  <span className={p.done ? `${ts.taskNumber} ${ts.taskNumberDone}` : ts.taskNumber} aria-hidden="true">
                    {p.number}
                  </span>
                  <span className={ts.taskBody}>
                    <span className={ts.taskTitle}>{p.title}</span>
                    <span id={`task-${p.id}-status`} className={phaseTagClass(p.state)}>
                      {PHASE_STATE_WORD[p.state]}
                    </span>
                    <span id={`task-${p.id}-summary`} className={ts.taskSummary}>
                      {p.summary}
                    </span>
                  </span>
                </a>
              </li>
            ))}
          </ol>
        </nav>

        <PhasePanel
          key={selectedId}
          ref={headingRef}
          tenantId={tenantId}
          detail={detail}
          consent={consentRead.state}
          funnel={funnel}
          phase={selected}
          open={open}
          onOpen={(id) => {
            setOpen(id);
            setFocusTick((n) => n + 1);
          }}
          onSelect={select}
          onChanged={onChanged}
          onUnrecorded={() => setUnrecorded(true)}
          onNotice={setNotice}
        />
      </div>

      <div className={ts.lifecycle}>
        <LifecyclePanel tenantId={tenantId} detail={detail} onChanged={onChanged} onUnrecorded={() => setUnrecorded(true)} onNotice={setNotice} />
      </div>
    </main>
  );
}
