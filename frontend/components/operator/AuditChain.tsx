'use client';

import { useCallback, useEffect, useState } from 'react';
import { Button } from '@/components/ui/Button';
import { bffRequest } from '@/lib/bff/browser';
import { OPERATOR_CSRF } from '@/lib/operator/browser';
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
  const [entries, setEntries] = useState<Entry[]>([]);
  const [next, setNext] = useState<number | null>(null);
  const [status, setStatus] = useState<'loading' | 'ok' | 'failed'>('loading');
  const [more, setMore] = useState(false);
  const [check, setCheck] = useState<Check>(null);
  const [checking, setChecking] = useState(false);

  const load = useCallback(async (after: number, first: boolean) => {
    const result = await bffRequest<Page>(`/api/bff/platform/audit?afterSeq=${after}&limit=50`, { csrf: OPERATOR_CSRF });
    if (!result.ok) {
      if (first) setStatus('failed');
      return;
    }
    setEntries((current) => (first ? result.data.entries : [...current, ...result.data.entries]));
    setNext(result.data.next);
    setStatus('ok');
  }, []);

  useEffect(() => {
    void load(0, true);
  }, [load]);

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
              <Button
                variant="neutral"
                busy={more}
                onClick={() => {
                  setMore(true);
                  void load(next, false).finally(() => setMore(false));
                }}
              >
                Load more
              </Button>
            </div>
          ) : null}
        </>
      ) : null}
    </main>
  );
}
