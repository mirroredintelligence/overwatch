'use client';

import { useState } from 'react';
import { useOperatorRead } from '@/lib/operator/browser';
import { deriveFunnel, type Consent, type FunnelStep } from '@/lib/operator/funnel';
import type { parseTenantDetail } from '@/lib/operator/views';
import { TENANT_STATUS_WORD } from '@/lib/operator/words';
import { GoLiveStep, LifecyclePanel, type Notice } from './TenantLifecycle';
import { AgreementsStep, InviteStep, OrganisationStep, ReachStep, RolesStep, SignInStep, TeamStep } from './TenantPanels';
import styles from '@/components/admin/admin.module.css';

// One partner organisation's page (TEN-083): a guided "Go live" funnel. Eight steps in order, each with one next action
// and a collapsed Details section for the technical identifiers, then what suspending or closing does. Every write is
// the operator's own. No secret is shown. The funnel's state is derived from the detail and the approval link the page
// already reads (`lib/operator/funnel.ts`); nothing new is written or stored for it.

type Detail = ReturnType<typeof parseTenantDetail>;
const STATE_WORD = { done: 'Done', next: 'Next', todo: 'To do' } as const;

export function TenantDetail({ tenantId }: { tenantId: string }) {
  const { state, reload } = useOperatorRead<Detail>(`/api/bff/platform/tenants/${tenantId}`);
  const consentRead = useOperatorRead<Consent>(`/api/bff/platform/tenants/${tenantId}/admin-consent`);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [unrecorded, setUnrecorded] = useState(false);

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
  const onChanged = () => {
    reload();
    consentRead.reload();
  };
  const step = (id: FunnelStep['id']): FunnelStep => funnel.steps.find((s) => s.id === id)!;
  const panel = (id: FunnelStep['id']) => ({ tenantId, detail, consent: consentRead.state, step: step(id), isNext: funnel.next === id, onChanged, onUnrecorded: () => setUnrecorded(true) });
  const nextStep = funnel.steps.find((s) => s.id === funnel.next);
  const stateOf = (s: FunnelStep) => (s.done ? 'done' : funnel.next === s.id ? 'next' : 'todo');
  return (
    <main className={styles.page}>
      <h1 className={styles.title}>{detail.tenant.displayName}</h1>
      <div className={styles.row}>
        <span className={detail.tenant.status === 'active' ? styles.tag : `${styles.tag} ${styles.tagDashed}`}>{TENANT_STATUS_WORD[detail.tenant.status] ?? detail.tenant.status}</span>
        <span className={styles.muted}>{`${funnel.doneCount} of ${funnel.total} steps done`}</span>
      </div>

      <nav aria-label="Go live progress">
        <ol className={styles.progress}>
          {funnel.steps.map((s) => (
            <li key={s.id} aria-current={funnel.next === s.id ? 'step' : undefined} data-state={stateOf(s)}>
              <a className={styles.link} href={`#step-${s.id}`}>{`${s.number}. ${s.title}`}</a>
              <span className={stateOf(s) === 'done' ? styles.tag : `${styles.tag} ${styles.tagDashed}`}>{STATE_WORD[stateOf(s)]}</span>
            </li>
          ))}
        </ol>
      </nav>
      {nextStep !== undefined && detail.tenant.status === 'provisioning' ? (
        <p className={styles.text} data-el="OP-NEXT-STEP">
          Next: <a className={styles.link} href={`#step-${nextStep.id}`}>{nextStep.title}</a>
        </p>
      ) : null}

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

      <OrganisationStep {...panel('organisation')} />
      <SignInStep {...panel('signin')} />
      <InviteStep {...panel('invite')} />
      <TeamStep {...panel('team')} />
      <RolesStep {...panel('roles')} />
      <ReachStep {...panel('reach')} />
      <AgreementsStep {...panel('agreements')} />
      <GoLiveStep tenantId={tenantId} detail={detail} onChanged={onChanged} onUnrecorded={() => setUnrecorded(true)} onNotice={setNotice} funnel={funnel} step={step('golive')} />
      <LifecyclePanel tenantId={tenantId} detail={detail} onChanged={onChanged} onUnrecorded={() => setUnrecorded(true)} onNotice={setNotice} />
    </main>
  );
}
