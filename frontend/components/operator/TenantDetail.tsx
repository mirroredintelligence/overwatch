'use client';

import { useEffect, useRef, useState } from 'react';
import { useOperatorRead } from '@/lib/operator/browser';
import { PageHeader } from '@/components/shell/PageHeader';
import { StageArea, StageGrid, StageLayer } from '@/components/ui/StageGrid';
import { StatusTag, type StatusTagVariant } from '@/components/ui/StatusTag';
import { deriveFunnel, type Consent, type PhaseId } from '@/lib/operator/funnel';
import type { parseTenantDetail } from '@/lib/operator/views';
import { TENANT_STATUS_WORD } from '@/lib/operator/words';
import { LifecyclePanel, type Notice } from './TenantLifecycle';
import { PhasePanel, PhaseTag } from './TenantPhases';
import styles from '@/components/admin/admin.module.css';
import ts from './Tenant.module.css';
import stage from './TenantStage.module.css';

// One partner organisation's page (TEN-083, board O4): a guided "Go live" on the stage grid. The five parts are
// buttons on the left (each with its status as a shape and a word and one line on where it stands; a finished
// part folds to one line, the next is outlined, later parts are dashed) and, beside it (under it on a phone), the
// open part: by default the first part that is not completed. Each part has its own layer on the stage; the ones
// that are not open are inert and aria-hidden, and only the open one is drawn. A completed part shows a short
// summary and a "Change" link. Every write is the operator's own. No secret is shown. The state is derived from
// the detail and the approval link the page already reads (`lib/operator/funnel.ts`); nothing new is written or
// stored for it.

type Detail = ReturnType<typeof parseTenantDetail>;

// The list is a fixed 400px (the board); the open part takes the rest. The grid does not change width between
// parts: what morphs is the parts (they fold) and the layers (they swap).
const TEMPLATES = ['minmax(0,25rem) minmax(0,1fr) 0px'] as const;
const GAPS = ['var(--space-5)'] as const;

const TENANT_VARIANT: Record<string, StatusTagVariant> = {
  provisioning: 'waiting',
  active: 'live',
  suspended: 'paused',
  offboarding: 'paused',
  offboarded: 'closed',
  purged: 'closed',
};

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

  const selectedIndex = funnel.phases.findIndex((p) => p.id === selectedId);

  return (
    <main className={stage.page}>
      <PageHeader title={detail.tenant.displayName}>
        <div className={stage.headRow}>
          <StatusTag variant={TENANT_VARIANT[detail.tenant.status] ?? 'todo'}>{TENANT_STATUS_WORD[detail.tenant.status] ?? detail.tenant.status}</StatusTag>
          {detail.tenant.status === 'provisioning' ? <span className={styles.muted}>{`${completed} of ${funnel.phases.length} parts completed`}</span> : null}
        </div>
      </PageHeader>

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

      <StageGrid stage={selectedIndex} templates={TEMPLATES} gaps={GAPS} className={stage.shell}>
        <StageArea name="list">
          <section aria-label="The five parts" className={stage.listInner}>
            <p className={stage.progress}>{`${completed} of ${funnel.phases.length} parts done`}</p>
            <ol className={stage.parts}>
              {funnel.phases.map((p) => (
                <li key={p.id}>
                  <button
                    type="button"
                    className={stage.part}
                    data-state={p.state}
                    aria-current={p.id === selectedId ? 'step' : undefined}
                    aria-describedby={`part-${p.id}-summary`}
                    onClick={() => select(p.id)}
                  >
                    <span className={stage.dot} data-state={p.state} data-next={p.id === funnel.nextPhase} aria-hidden="true">
                      {p.done ? '✓' : p.number}
                    </span>
                    <span className={stage.partBody}>
                      <span className={stage.partTitle}>{p.title}</span>
                      <span id={`part-${p.id}-summary`} className={stage.partSummary}>
                        {p.summary}
                      </span>
                    </span>
                    <span className={stage.partTag}>
                      <PhaseTag state={p.state} />
                    </span>
                  </button>
                </li>
              ))}
            </ol>
            <p className={stage.fold}>Parts you finish fold to one line. You can reopen any of them.</p>
          </section>
        </StageArea>
        <StageArea name="stage">
          {funnel.phases.map((p, i) => (
            <StageLayer key={p.id} index={i} current={selectedIndex}>
              {p.id === selectedId ? (
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
              ) : null}
            </StageLayer>
          ))}
        </StageArea>
        <StageArea name="side" />
      </StageGrid>

      <div className={ts.lifecycle}>
        <LifecyclePanel tenantId={tenantId} detail={detail} onChanged={onChanged} onUnrecorded={() => setUnrecorded(true)} onNotice={setNotice} />
      </div>
    </main>
  );
}
