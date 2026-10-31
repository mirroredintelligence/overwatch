'use client';

import { useState } from 'react';
import { Button } from '@/components/ui/Button';
import { bffRequest } from '@/lib/bff/browser';
import { OPERATOR_CSRF, useOperatorRead } from '@/lib/operator/browser';
import type { parseAudit } from '@/lib/operator/views';
import { auditWord } from '@/lib/operator/words';
import { whenText } from '@/lib/tenantAdmin/words';
import styles from '@/components/admin/admin.module.css';

// The platform audit chain (TEN-083, DEC-1002): what the platform's own people did, oldest first, a page at a
// time, and a check that the whole chain is intact. A chain that is broken is said plainly, as an alert, and a
// check that could not be made never says "intact".

type Page = ReturnType<typeof parseAudit>;
type Entry = Page['entries'][number];
type Check = { kind: 'intact' } | { kind: 'broken' } | { kind: 'failed' } | null;

export function AuditChain() {
  const first = useOperatorRead<Page>('/api/bff/platform/audit?afterSeq=0&limit=50');
  const [more, setMore] = useState<{ entries: Entry[]; next: number | null } | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [check, setCheck] = useState<Check>(null);
  const [checking, setChecking] = useState(false);

  const entries = first.state.status === 'ok' ? [...first.state.data.entries, ...(more?.entries ?? [])] : [];
  const next = more !== null ? more.next : first.state.status === 'ok' ? first.state.data.next : null;
  const status = first.state.status;

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
    setCheck(null);
    const result = await bffRequest<{ intact: boolean }>('/api/bff/platform/audit/verification', { csrf: OPERATOR_CSRF });
    setChecking(false);
    setCheck(!result.ok ? { kind: 'failed' } : result.data.intact ? { kind: 'intact' } : { kind: 'broken' });
  }

  return (
    <main className={styles.page}>
      <h1 className={styles.title}>Audit chain</h1>
      <p className={styles.lede}>What the platform’s own people did, oldest first. Each step is linked to the one before it, so a change to the past shows.</p>
      <div className={styles.actions}>
        <Button variant="secondary" busy={checking} onClick={() => void verify()} dataEl="OP-AUDIT-CHECK-BTN">
          Check the chain
        </Button>
      </div>
      {check?.kind === 'intact' ? (
        <p role="status" className={styles.ok}>
          The chain is intact.
        </p>
      ) : null}
      {check?.kind === 'broken' ? (
        <p role="alert" className={styles.problem}>
          The chain is not intact. Do not rely on it. Tell the person who looks after the platform record now.
        </p>
      ) : null}
      {check?.kind === 'failed' ? (
        <p role="alert" className={styles.problem}>
          The check could not be made. Try again.
        </p>
      ) : null}
      {status === 'loading' ? <p className={styles.muted}>Loading the audit chain.</p> : null}
      {status === 'failed' ? (
        <p role="alert" className={styles.problem}>
          We could not load the audit chain.
        </p>
      ) : null}
      {status === 'ok' ? (
        <>
          <div className={styles.scroll}>
            <table className={styles.table}>
              <caption>The platform audit chain</caption>
              <thead>
                <tr>
                  <th scope="col">No.</th>
                  <th scope="col">When</th>
                  <th scope="col">What happened</th>
                  <th scope="col">Account</th>
                  <th scope="col">Tenant</th>
                </tr>
              </thead>
              <tbody>
                {entries.map((entry) => (
                  <tr key={entry.seq}>
                    <td className={styles.num}>{entry.seq}</td>
                    <td>{whenText(entry.at)}</td>
                    <td>{auditWord(entry.action)}</td>
                    <td>{entry.principalRef}</td>
                    <td>{entry.tenantId ?? '-'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {next !== null ? (
            <div className={styles.actions}>
              <Button variant="neutral" busy={loadingMore} onClick={() => void loadMore(next)}>
                Load more
              </Button>
            </div>
          ) : null}
        </>
      ) : null}
    </main>
  );
}
