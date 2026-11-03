'use client';

import { useState } from 'react';
import { TimelineList, type TimelineItem } from '@/components/blocks/TimelineList';
import { Button } from '@/components/ui/Button';
import { Loading, SkeletonRows } from '@/components/ui/Skeleton';
import { StatusTag } from '@/components/ui/StatusTag';
import { bffRequest } from '@/lib/bff/browser';
import { OPERATOR_CSRF, useOperatorRead } from '@/lib/operator/browser';
import type { parseAudit } from '@/lib/operator/views';
import { auditWord } from '@/lib/operator/words';
import { whenText } from '@/lib/tenantAdmin/words';
import styles from './AuditChain.module.css';

// The platform audit chain (TEN-083, DEC-1002): what the platform's own people did, oldest first, a page at a
// time, and a check that the whole chain is intact. A chain that is broken is said plainly, as an alert, and no
// entry is hidden because of it; a check that could not be made never says "intact".
//
// The groups are a view over the entries already loaded: they change what is listed, never the check.

type Page = ReturnType<typeof parseAudit>;
type Entry = Page['entries'][number];
type Check = { kind: 'intact' } | { kind: 'broken' } | { kind: 'failed' } | null;

const GROUPS = [
  { id: 'everything', label: 'Everything', matches: () => true },
  { id: 'sign-ins', label: 'Sign-ins', matches: (action: string) => action.startsWith('operator-') },
  { id: 'organisations', label: 'Organisations', matches: (action: string) => action.startsWith('tenant-') },
  { id: 'support', label: 'Support access', matches: (action: string) => action.startsWith('support-') },
] as const;

type GroupId = (typeof GROUPS)[number]['id'];

// A support request still waiting for the tenant's administrator is the one entry that asks for something.
const ATTENTION = 'support-ticket-requested';

function detailOf(entry: Entry): string {
  return entry.tenantId === null ? `Account ${entry.principalRef}` : `Account ${entry.principalRef} · Tenant ${entry.tenantId}`;
}

export function AuditChain() {
  const first = useOperatorRead<Page>('/api/bff/platform/audit?afterSeq=0&limit=50');
  const [more, setMore] = useState<{ entries: Entry[]; next: number | null } | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [group, setGroup] = useState<GroupId>('everything');
  const [check, setCheck] = useState<Check>(null);
  const [asked, setAsked] = useState(false);
  const [checking, setChecking] = useState(false);

  const entries = first.state.status === 'ok' ? [...first.state.data.entries, ...(more?.entries ?? [])] : [];
  const next = more !== null ? more.next : first.state.status === 'ok' ? first.state.data.next : null;
  const status = first.state.status;
  const selected = GROUPS.find((candidate) => candidate.id === group) ?? GROUPS[0];
  const visible = entries.filter((entry) => selected.matches(entry.action));

  const items: TimelineItem[] = visible.map((entry) => ({
    id: String(entry.seq),
    title: auditWord(entry.action),
    detail: detailOf(entry),
    time: whenText(entry.at),
    at: entry.at || undefined,
    tone: entry.action === ATTENTION ? 'attention' : 'normal',
  }));

  async function loadMore(after: number) {
    if (loadingMore) return;
    setLoadingMore(true);
    const result = await bffRequest<Page>(`/api/bff/platform/audit?afterSeq=${after}&limit=50`, { csrf: OPERATOR_CSRF });
    setLoadingMore(false);
    if (result.ok) setMore((current) => ({ entries: [...(current?.entries ?? []), ...result.data.entries], next: result.data.next }));
  }

  async function verify() {
    if (checking) return;
    setChecking(true);
    setAsked(true);
    setCheck(null);
    const result = await bffRequest<{ intact: boolean }>('/api/bff/platform/audit/verification', { csrf: OPERATOR_CSRF });
    setChecking(false);
    setCheck(!result.ok ? { kind: 'failed' } : result.data.intact ? { kind: 'intact' } : { kind: 'broken' });
  }

  return (
    <main className={styles.page}>
      <h1 className={styles.title}>Audit chain</h1>
      {status === 'loading' ? (
        <Loading label="Loading the audit chain.">
          <SkeletonRows count={4} />
        </Loading>
      ) : null}
      {status === 'failed' ? (
        <p role="alert" className={styles.problem}>
          We could not load the audit chain.
        </p>
      ) : null}
      {status === 'ok' ? (
        <div className={styles.layout}>
          <section aria-label="Entries" className={styles.entries}>
            <p className={styles.lede}>What the platform’s own people did. Each entry is linked to the one before it, so a change to the past shows.</p>
            {entries.length > 0 ? (
              <div role="group" aria-label="Show" className={styles.filters}>
                {GROUPS.map((candidate) => (
                  <button
                    key={candidate.id}
                    type="button"
                    className={styles.filter}
                    aria-pressed={candidate.id === group}
                    onClick={() => setGroup(candidate.id)}
                  >
                    {candidate.label}
                  </button>
                ))}
                <span className={styles.sort}>Oldest first</span>
              </div>
            ) : null}
            {entries.length === 0 ? <p className={styles.muted}>Nothing has been recorded yet.</p> : null}
            {entries.length > 0 && visible.length === 0 ? <p className={styles.muted}>Nothing in this group yet.</p> : null}
            {visible.length > 0 ? <TimelineList label="Entries" items={items} line /> : null}
            {next !== null ? (
              <Button variant="neutral" busy={loadingMore} onClick={() => void loadMore(next)}>
                Show later entries
              </Button>
            ) : null}
          </section>

          <aside aria-label="Chain check" className={styles.check}>
            <div className={styles.card} data-state={check?.kind ?? 'none'}>
              {!asked ? <p className={styles.text}>The chain has not been checked yet. Check it to see whether every entry still matches the one before it.</p> : null}
              {check?.kind === 'intact' ? (
                <div role="status" className={styles.intact}>
                  <StatusTag variant="done">The chain is intact.</StatusTag>
                  <p className={styles.text}>Every entry was checked against the one before it.</p>
                </div>
              ) : null}
              {check?.kind === 'broken' ? (
                <div role="alert" className={styles.broken}>
                  <StatusTag variant="over">The chain is not intact.</StatusTag>{' '}
                  <span className={styles.problem}>Do not rely on it. Tell the person who looks after the platform record now.</span>
                </div>
              ) : null}
              {check?.kind === 'failed' ? (
                <div role="alert" className={styles.broken}>
                  <StatusTag variant="problem">The check could not be made.</StatusTag>{' '}
                  <span className={styles.problem}>Try again.</span>
                </div>
              ) : null}
              <Button variant="secondary" busy={checking} onClick={() => void verify()} dataEl="OP-AUDIT-CHECK-BTN">
                {asked ? 'Check it again' : 'Check the chain'}
              </Button>
            </div>
          </aside>
        </div>
      ) : null}
    </main>
  );
}
