'use client';

import Link from 'next/link';
import { useState } from 'react';
import { Button } from '@/components/ui/Button';
import { Dialog } from '@/components/ui/Dialog';
import { adminSend, useAdminRead, useSubmitKey } from '@/lib/tenantAdmin/browser';
import type { ConfigView, SettingSpec } from '@/lib/tenantAdmin/views';
import { humaniseKey, whenText } from '@/lib/tenantAdmin/words';
import { ConfigDiff } from './ConfigDiff';
import { STATUS_WORD } from './ConfigVersions';
import styles from './admin.module.css';

// One version of the settings (TEN-076): what it changes against the version it replaces, who has approved
// it (as a count, and "you"), and the approval. The author of a clinical change cannot approve it, and the
// page says so rather than showing a button that would be refused; a person who has approved cannot again.

type Approved = { version: number; status: ConfigView['status']; approvals: number; approvalsRequired: number };

export function VersionDetail({ version }: { version: number }) {
  const one = useAdminRead<ConfigView>(`/api/bff/tenant/config/versions/${version}`);
  const all = useAdminRead<{ versions: ConfigView[] }>('/api/bff/tenant/config/versions');
  const specs = useAdminRead<{ settings: SettingSpec[] }>('/api/bff/tenant/settings');
  const [asking, setAsking] = useState(false);
  const [done, setDone] = useState<Approved | null>(null);
  const [failure, setFailure] = useState('');
  const [busy, setBusy] = useState(false);
  const submitKey = useSubmitKey();

  if (one.state.status === 'failed') {
    return (
      <main className={styles.page}>
        <h1 className={styles.title}>{`Version ${version}`}</h1>
        <p role="alert" className={styles.problem}>
          {one.state.http === 404 ? 'We could not find that version.' : 'We could not load this version.'}
        </p>
      </main>
    );
  }
  if (one.state.status === 'loading' || all.state.status === 'loading' || specs.state.status === 'loading') {
    return (
      <main className={styles.page}>
        <h1 className={styles.title}>{`Version ${version}`}</h1>
        <p className={styles.muted}>Loading this version.</p>
      </main>
    );
  }
  if (all.state.status === 'failed' || specs.state.status === 'failed') {
    return (
      <main className={styles.page}>
        <h1 className={styles.title}>{`Version ${version}`}</h1>
        <p role="alert" className={styles.problem}>
          We could not load this version.
        </p>
      </main>
    );
  }

  const v = one.state.data;
  const base = v.replaces === null ? null : (all.state.data.versions.find((other) => other.version === v.replaces) ?? null);
  const clinical = v.clinicalKeys.length > 0;
  const live = v.status === 'draft' || v.status === 'pending-approval';
  const youWrote = clinical && v.authoredByYou;
  const canApprove = live && !v.approvedByYou && !youWrote && done === null;

  async function approve() {
    if (busy) return;
    setBusy(true);
    setFailure('');
    const result = await adminSend<Approved>('POST', `/api/bff/tenant/config/versions/${version}/approval`, undefined, submitKey.key());
    setBusy(false);
    setAsking(false);
    if (result.ok) {
      submitKey.fresh();
      setDone(result.data);
      one.reload();
      return;
    }
    setFailure('This version cannot be approved by you now. Reload the page to see where it stands.');
  }

  return (
    <main className={styles.page}>
      <h1 className={styles.title}>{`Version ${v.version}`}</h1>
      <div className={styles.row}>
        <span className={v.status === 'current' ? styles.tag : `${styles.tag} ${styles.tagDashed}`}>{STATUS_WORD[v.status]}</span>
        <span className={styles.text}>{`${v.approvals} of ${v.approvalsRequired} approvals`}</span>
      </div>
      <p className={styles.muted}>{`Written ${whenText(v.createdAt)}. In force from ${whenText(v.effectiveFrom)}.`}</p>

      <ConfigDiff changedKeys={v.changedKeys} before={base?.values ?? {}} after={v.values} specs={specs.state.data.settings} />

      {done !== null ? (
        <p role="status" className={styles.ok}>
          {done.status === 'current' ? `You approved version ${done.version}. It is now in force.` : `You approved version ${done.version}. ${done.approvals} of ${done.approvalsRequired} approvals.`}
        </p>
      ) : null}
      {failure !== '' ? (
        <p role="alert" className={styles.problem}>
          {failure}
        </p>
      ) : null}
      {youWrote && live ? <p className={styles.warn}>You wrote this change. It needs two other people to approve it.</p> : null}
      {v.approvedByYou && live && done === null ? <p className={styles.text}>You have approved this version.</p> : null}
      {canApprove ? (
        <div className={styles.actions}>
          <Button variant="primary" onClick={() => setAsking(true)} dataEl="ADMIN-APPROVE-BTN">
            {`Approve version ${v.version}`}
          </Button>
        </div>
      ) : null}
      <p className={styles.text}>
        <Link className={styles.link} href="/admin/config">
          All versions
        </Link>
      </p>

      {asking ? (
        <Dialog title={`Approve version ${v.version}?`} sub="Your approval is recorded against your account." onClose={() => setAsking(false)}>
          <ul className={styles.list}>
            {v.changedKeys.map((key) => (
              <li key={key}>{humaniseKey(key)}</li>
            ))}
          </ul>
          <div className={styles.actions}>
            <Button variant="primary" busy={busy} onClick={() => void approve()} dataEl="ADMIN-APPROVE-CONFIRM-BTN">
              Confirm approval
            </Button>
            <Button variant="neutral" onClick={() => setAsking(false)}>
              Cancel
            </Button>
          </div>
        </Dialog>
      ) : null}
    </main>
  );
}
