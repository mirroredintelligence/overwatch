'use client';

import { useState } from 'react';
import { useOperatorRead } from '@/lib/operator/browser';
import type { parseTenantDetail } from '@/lib/operator/views';
import { organisationTypeWord, TENANT_STATUS_WORD } from '@/lib/operator/words';
import { ActivationPanel, LifecyclePanel, type Notice } from './TenantLifecycle';
import { DirectoryPanel, HostPanel, InvitationPanel, NumbersPanel, ReferencesPanel } from './TenantPanels';
import styles from '@/components/admin/admin.module.css';

// One tenant's page (TEN-083): provisioning (the address, the text numbers, the agreement references, the
// directory, the first administrator), what activation waits for, and the life of the tenant. Every write is
// the operator's own. No secret is shown: a number says only whether it has an auth token.

type Detail = ReturnType<typeof parseTenantDetail>;

export function TenantDetail({ tenantId }: { tenantId: string }) {
  const { state, reload } = useOperatorRead<Detail>(`/api/bff/platform/tenants/${tenantId}`);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [unrecorded, setUnrecorded] = useState(false);

  if (state.status === 'loading') {
    return (
      <main className={styles.page}>
        <p className={styles.muted}>Loading the tenant.</p>
      </main>
    );
  }
  if (state.status === 'failed') {
    return (
      <main className={styles.page}>
        <p role="alert" className={styles.problem}>
          {state.http === 404 ? 'We could not find that tenant.' : 'We could not load the tenant.'}
        </p>
      </main>
    );
  }
  const detail = state.data;
  const panel = { tenantId, detail, onChanged: reload, onUnrecorded: () => setUnrecorded(true) };
  return (
    <main className={styles.page}>
      <h1 className={styles.title}>{detail.tenant.displayName}</h1>
      <div className={styles.row}>
        <span className={detail.tenant.status === 'active' ? styles.tag : `${styles.tag} ${styles.tagDashed}`}>{TENANT_STATUS_WORD[detail.tenant.status] ?? detail.tenant.status}</span>
        <span className={styles.muted}>{detail.tenant.id}</span>
      </div>
      <dl className={styles.facts}>
        <dt>Legal name</dt>
        <dd>{detail.tenant.legalName}</dd>
        <dt>Type</dt>
        <dd>{organisationTypeWord(detail.tenant.organisationType)}</dd>
        <dt>ODS code</dt>
        <dd>{detail.tenant.odsCode ?? '-'}</dd>
        <dt>Time zone</dt>
        <dd>{detail.tenant.timeZone}</dd>
      </dl>

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

      <ActivationPanel {...panel} onNotice={setNotice} />
      <HostPanel {...panel} />
      <NumbersPanel {...panel} />
      <ReferencesPanel {...panel} />
      <DirectoryPanel {...panel} />
      <InvitationPanel {...panel} />
      <LifecyclePanel {...panel} onNotice={setNotice} />
    </main>
  );
}
