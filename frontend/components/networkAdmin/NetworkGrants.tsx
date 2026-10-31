'use client';

import { useState } from 'react';
import { Button } from '@/components/ui/Button';
import { Card } from '@/components/ui/Card';
import { Dialog } from '@/components/ui/Dialog';
import { BASE, post, useAdminRead, useNotice, type GrantsRead } from '@/lib/networkAdmin/browser';
import type { GrantRow } from '@/lib/networkAdmin/views';
import { approvalWord, dateText, PURPOSE_WORD, SCOPE_WORD, waitsForOwner } from '@/lib/networkAdmin/words';
import styles from '../admin/admin.module.css';
import { OwnedNetworkGate } from './OwnedNetworkGate';

// The grants of the network (TEN-080, design N1: NetworkGrants). The owner approves or declines a grant that
// waits for it. A grant takes two approvals, the organisation's and the owner's, from two different people;
// the owner never ends a member's grant (only the grantor does, DEC-132 item 3) and sees no field of a
// member's data: the screen shows who, which kind, for what, from when and where the approvals stand.

export function NetworkGrants() {
  return (
    <main className={styles.page}>
      <h1 className={styles.title}>Grants</h1>
      <OwnedNetworkGate>{(query) => <Grants query={query} />}</OwnedNetworkGate>
    </main>
  );
}

function Grants({ query }: { query: string }) {
  const { state, reload } = useAdminRead<GrantsRead>(`${BASE}/grants${query}`);
  const { notice, say } = useNotice();
  const [busy, setBusy] = useState<string | null>(null);
  const [declining, setDeclining] = useState<GrantRow | null>(null);

  async function approve(grant: GrantRow) {
    if (busy !== null) return;
    setBusy(grant.id);
    const result = await post<{ effective: boolean }>(`${BASE}/grants/${encodeURIComponent(grant.id)}/approve`, '');
    setBusy(null);
    if (result.ok) {
      say(true, result.data.effective ? 'Approved. The grant is now in force.' : 'Your approval is recorded. The grant starts when the organisation has approved too.');
      reload();
    } else if (result.status === 409) {
      say(false, 'That could not be done. If you gave the other approval yourself, another person must give this one.');
    } else {
      say(false, 'The approval could not be recorded. Try again.');
    }
  }

  if (state.status === 'loading') return <p className={styles.muted}>Loading the grants.</p>;
  if (state.status === 'failed') {
    return (
      <p role="alert" className={styles.problem}>
        We could not load the grants.
      </p>
    );
  }
  return (
    <>
      {notice !== null ? (
        <p role={notice.ok ? 'status' : 'alert'} className={notice.ok ? styles.ok : styles.problem}>
          {notice.text}
        </p>
      ) : null}
      <Card heading={state.data.network.name}>
        <div className={styles.scroll}>
          <table className={styles.table} data-el="NADM-GRANTS-TABLE">
            <caption>Grants</caption>
            <thead>
              <tr>
                <th scope="col">Organisation</th>
                <th scope="col">Scope</th>
                <th scope="col">Purpose</th>
                <th scope="col">From</th>
                <th scope="col">To</th>
                <th scope="col">Approval</th>
                <th scope="col">Version</th>
                <th scope="col">
                  <span className={styles.srOnly}>Action</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {state.data.grants.length === 0 ? (
                <tr>
                  <td colSpan={8}>Nothing here yet.</td>
                </tr>
              ) : (
                state.data.grants.map((grant) => (
                  <tr key={grant.id} data-row-ref={grant.id}>
                    <td>{grant.organisation}</td>
                    <td>{SCOPE_WORD[grant.scope]}</td>
                    <td>{PURPOSE_WORD}</td>
                    <td>{dateText(grant.effectiveFrom)}</td>
                    <td>{grant.effectiveTo === null ? 'No end date' : dateText(grant.effectiveTo)}</td>
                    <td>{approvalWord(grant)}</td>
                    <td>{grant.version}</td>
                    <td>
                      {waitsForOwner(grant) ? (
                        <div className={styles.actions}>
                          <Button variant="primary" busy={busy === grant.id} dataEl="NADM-GRANT-APPROVE-BTN" onClick={() => void approve(grant)}>
                            Approve<span className={styles.srOnly}>{` ${SCOPE_WORD[grant.scope]} grant of ${grant.organisation}`}</span>
                          </Button>
                          <Button variant="neutral" dataEl="NADM-GRANT-DECLINE-BTN" onClick={() => setDeclining(grant)}>
                            Decline<span className={styles.srOnly}>{` ${SCOPE_WORD[grant.scope]} grant of ${grant.organisation}`}</span>
                          </Button>
                        </div>
                      ) : null}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </Card>
      {declining !== null ? (
        <DeclineDialog
          grant={declining}
          onClose={() => setDeclining(null)}
          onDeclined={() => {
            setDeclining(null);
            say(true, 'Grant declined.');
            reload();
          }}
        />
      ) : null}
    </>
  );
}

function DeclineDialog({ grant, onClose, onDeclined }: { grant: GrantRow; onClose: () => void; onDeclined: () => void }) {
  const [problem, setProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function decline() {
    if (busy) return;
    setBusy(true);
    setProblem(null);
    const result = await post(`${BASE}/grants/${encodeURIComponent(grant.id)}/decline`, '');
    setBusy(false);
    if (result.ok) onDeclined();
    else setProblem('The grant could not be declined. Try again.');
  }

  return (
    <Dialog title="Decline this grant?" sub={`${SCOPE_WORD[grant.scope]} for ${grant.organisation}`} onClose={onClose}>
      <p className={styles.text}>A declined grant is closed. The organisation can propose a new one.</p>
      {problem !== null ? (
        <p role="alert" className={styles.problem}>
          {problem}
        </p>
      ) : null}
      <div className={styles.actions}>
        <Button variant="primary" busy={busy} dataEl="NADM-GRANT-DECLINE-CONFIRM-BTN" onClick={() => void decline()}>
          Decline
        </Button>
        <Button variant="neutral" onClick={onClose} dataEl="SCREENS-BOARD-CANCEL-BTN">
          Cancel
        </Button>
      </div>
    </Dialog>
  );
}
