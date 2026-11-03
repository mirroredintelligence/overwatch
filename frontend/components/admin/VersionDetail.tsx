'use client';

import Link from 'next/link';
import { useState } from 'react';
import { ApprovalMeter } from '@/components/blocks/ApprovalMeter';
import { Button } from '@/components/ui/Button';
import { Dialog } from '@/components/ui/Dialog';
import { StatusTag, type StatusTagVariant } from '@/components/ui/StatusTag';
import { adminSend, useAdminRead, useSubmitKey } from '@/lib/tenantAdmin/browser';
import type { ConfigView, SettingSpec } from '@/lib/tenantAdmin/views';
import { humaniseKey, whenText } from '@/lib/tenantAdmin/words';
import { ConfigDiff } from './ConfigDiff';
import { STATUS_WORD } from './ConfigVersions';
import { Loading, SkeletonRows } from '@/components/ui/Skeleton';
import styles from './VersionDetail.module.css';

// One version of the settings (TEN-076, board A3): what it changes against the version it replaces on the left;
// on the right who has approved it (as a count, and "you") and the approval. The author of a clinical change
// cannot approve it, and the page says so in words (to the author, and to the approver) rather than offering a
// button that would be refused; a person who has approved cannot again. There is no call to withdraw a draft, so
// the page says to ask a platform operator.

type Approved = { version: number; status: ConfigView['status']; approvals: number; approvalsRequired: number };

const VARIANT: Record<ConfigView['status'], StatusTagVariant> = {
  draft: 'todo',
  'pending-approval': 'waiting',
  current: 'live',
  superseded: 'closed',
};

function Back() {
  return (
    <Link className={styles.back} href="/admin/config">
      <span aria-hidden="true">‹&nbsp;</span>All versions
    </Link>
  );
}

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
        <Back />
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
        <Back />
        <h1 className={styles.title}>{`Version ${version}`}</h1>
        <Loading label="Loading this version.">
          <SkeletonRows count={3} />
        </Loading>
      </main>
    );
  }
  if (all.state.status === 'failed' || specs.state.status === 'failed') {
    return (
      <main className={styles.page}>
        <Back />
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
  const statusWord = live ? `${STATUS_WORD[v.status]} · ${v.approvals} of ${v.approvalsRequired}` : STATUS_WORD[v.status];
  const meta = [
    `Written ${whenText(v.createdAt)}`,
    v.replaces === null ? '' : `replaces version ${v.replaces}`,
    v.effectiveFrom === null ? '' : `in force from ${whenText(v.effectiveFrom)}`,
  ].filter((part) => part !== '');

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
      <div className={styles.layout}>
        <section aria-label="What changed" className={styles.main}>
          <Back />
          <div className={styles.headRow}>
            <h1 className={styles.title}>{`Version ${v.version}`}</h1>
            <StatusTag variant={VARIANT[v.status]}>{statusWord}</StatusTag>
            {clinical ? <span className={styles.kind}>Clinical</span> : null}
          </div>
          <p className={styles.meta}>{meta.join(' · ')}</p>
          <ConfigDiff changedKeys={v.changedKeys} before={base?.values ?? {}} after={v.values} specs={specs.state.data.settings} />
        </section>

        <aside aria-label="Approval" className={styles.aside}>
          <div className={styles.card}>
            <h2 className={styles.cardTitle}>Approval</h2>
            <ApprovalMeter given={v.approvals} needed={v.approvalsRequired} />
            {live && clinical && !youWrote ? <p className={styles.rule}>Approvals must come from people other than the one who wrote it.</p> : null}
            {v.approvedByYou && live && done === null ? <p className={styles.text}>You have approved this version.</p> : null}
          </div>

          {done !== null ? (
            <p role="status" className={styles.ok}>
              {done.status === 'current'
                ? `You approved version ${done.version}. It is now in force.`
                : `You approved version ${done.version}. ${done.approvals} of ${done.approvalsRequired} approvals.`}
            </p>
          ) : null}
          {failure !== '' ? (
            <p role="alert" className={styles.problem}>
              {failure}
            </p>
          ) : null}
          {youWrote && live ? (
            <p className={styles.author}>
              <b>You wrote this change.</b> You cannot approve it. Ask another administrator, or someone in a role that can approve.
            </p>
          ) : null}

          {live ? (
            <div className={styles.actions}>
              {canApprove ? (
                <Button variant="primary" onClick={() => setAsking(true)} dataEl="ADMIN-APPROVE-BTN">
                  {`Approve version ${v.version}`}
                </Button>
              ) : youWrote ? (
                <Button variant="primary" disabled dataEl="ADMIN-APPROVE-BTN">
                  Approve (not for the author)
                </Button>
              ) : null}
              <p className={styles.text}>Ask a platform operator to withdraw this draft.</p>
            </div>
          ) : null}
        </aside>
      </div>

      {asking ? (
        <Dialog title={`Approve version ${v.version}?`} sub="Your approval is recorded against your account." onClose={() => setAsking(false)}>
          <ul className={styles.list}>
            {v.changedKeys.map((key) => (
              <li key={key}>{humaniseKey(key)}</li>
            ))}
          </ul>
          <div className={styles.dialogActions}>
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
