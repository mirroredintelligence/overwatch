'use client';

import { useEffect, useId, useRef, useState } from 'react';
import { Button } from '@/components/ui/Button';
import { Chip } from '@/components/ui/Chip';
import { Loading, SkeletonRows } from '@/components/ui/Skeleton';
import { StatusTag, type StatusTagVariant } from '@/components/ui/StatusTag';
import { BASE, post, useAdminRead, useNotice, type GrantsRead } from '@/lib/networkAdmin/browser';
import type { GrantRow } from '@/lib/networkAdmin/views';
import { approvalWord, dateText, PURPOSE_WORD, SCOPE_WORD, waitsForOwner } from '@/lib/networkAdmin/words';
import styles from './NetworkGrants.module.css';
import { OwnedNetworkGate } from './OwnedNetworkGate';

// The grants of the network (TEN-080, design NGrants). The owner approves or declines a grant that waits for it,
// and filters the grants by where their two approvals stand. A grant takes two approvals, the organisation's and
// the owner's, from two different people; the owner never ends a member's grant (only the grantor does, DEC-132
// item 3) and sees no field of a member's data: the table shows who, which kind, from when and where the approvals
// stand. A decline asks first, in place, under the table.

export function NetworkGrants() {
  return (
    <main className={styles.page}>
      <h1 className={styles.title}>Grants</h1>
      <OwnedNetworkGate>{(query) => <Grants query={query} />}</OwnedNetworkGate>
    </main>
  );
}

type Filter = 'mine' | 'organisation' | 'approved' | 'declined';
const FILTERS: readonly (readonly [Filter, string])[] = [
  ['mine', 'Waiting for me'],
  ['organisation', 'Waiting for the organisation'],
  ['approved', 'Approved'],
  ['declined', 'Declined'],
];
const HOLDS: Readonly<Record<Filter, (grant: GrantRow) => boolean>> = {
  mine: (grant) => waitsForOwner(grant),
  organisation: (grant) => grant.status === 'owner-approved',
  approved: (grant) => grant.status === 'approved',
  declined: (grant) => grant.status === 'declined',
};

/** The shape and word of where a grant's approvals stand (the word is the approval, the shape is decoration). */
function approvalTag(grant: GrantRow): StatusTagVariant {
  if (waitsForOwner(grant)) return 'waiting';
  if (grant.status === 'owner-approved') return 'todo';
  if (grant.status === 'approved') return 'done';
  return 'closed';
}

function Grants({ query }: { query: string }) {
  const { state, reload } = useAdminRead<GrantsRead>(`${BASE}/grants${query}`);
  const { notice, say } = useNotice();
  const [busy, setBusy] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>('mine');
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

  if (state.status === 'loading') {
    return (
      <Loading label="Loading the grants.">
        <SkeletonRows count={3} />
      </Loading>
    );
  }
  if (state.status === 'failed') {
    return (
      <p role="alert" className={styles.problem}>
        We could not load the grants.
      </p>
    );
  }
  const grants = state.data.grants;
  const shown = grants.filter(HOLDS[filter]);
  return (
    <>
      {notice !== null ? (
        <p role={notice.ok ? 'status' : 'alert'} className={notice.ok ? styles.ok : styles.problem}>
          {notice.text}
        </p>
      ) : null}
      <div className={styles.columns}>
        <div className={styles.column}>
          <div role="group" aria-label="Which grants" className={styles.chips}>
            {FILTERS.map(([id, label]) => (
              <Chip key={id} pressed={filter === id} onPressedChange={() => setFilter(id)}>
                {`${label} ${grants.filter(HOLDS[id]).length}`}
              </Chip>
            ))}
          </div>
          <section className={styles.card}>
            <div className={styles.scroll}>
              <table className={styles.table} data-el="NADM-GRANTS-TABLE">
                <caption className={styles.srOnly}>Grants</caption>
                <thead>
                  <tr>
                    <th scope="col">Organisation</th>
                    <th scope="col">Scope</th>
                    <th scope="col">From</th>
                    <th scope="col">Approval</th>
                    <th scope="col">
                      <span className={styles.srOnly}>Action</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {shown.length === 0 ? (
                    <tr>
                      <td colSpan={5}>
                        Nothing here yet.
                        <span className={styles.muted}>{' When an organisation agrees to share, it appears here for you to approve.'}</span>
                      </td>
                    </tr>
                  ) : (
                    shown.map((grant) => (
                      <tr key={grant.id} data-row-ref={grant.id}>
                        <td>{grant.organisation}</td>
                        <td>{SCOPE_WORD[grant.scope]}</td>
                        <td>{dateText(grant.effectiveFrom)}</td>
                        <td>
                          <StatusTag variant={approvalTag(grant)}>{approvalWord(grant)}</StatusTag>
                        </td>
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
                          ) : grant.status === 'approved' && grant.effectiveTo !== null ? (
                            `to ${dateText(grant.effectiveTo)}`
                          ) : null}
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
            {declining !== null ? (
              <DeclineConfirm
                grant={declining}
                onClose={() => setDeclining(null)}
                onDeclined={() => {
                  setDeclining(null);
                  say(true, 'Grant declined.');
                  reload();
                }}
              />
            ) : null}
          </section>
        </div>
        <div className={styles.column}>
          <section className={styles.card}>
            <h2 className={styles.eyebrow}>What each scope shares</h2>
            <ul className={styles.scopes}>
              <li>
                <span aria-hidden="true" className={styles.bullet}>
                  ●
                </span>
                <div>
                  <b>Capacity</b>Status and figure of each listed service, with the time reported.
                </div>
              </li>
              <li>
                <span aria-hidden="true" className={styles.bullet}>
                  ●
                </span>
                <div>
                  <b>Directory</b>Service name, category, district, opening hours and service line.
                </div>
              </li>
              <li>
                <span aria-hidden="true" className={styles.bullet}>
                  ●
                </span>
                <div>
                  <b>Criteria</b>The current version only: what is accepted, not accepted, ages, districts.
                </div>
              </li>
            </ul>
          </section>
          <section className={styles.never}>
            <h2 className={styles.eyebrowDark}>Never shared</h2>
            <p className={styles.neverText}>
              {`Anything about a patient or a person: cases, bookings, reporters’ numbers, comments, audit. Each grant is for one purpose, "${PURPOSE_WORD}", and has dates.`}
            </p>
          </section>
          <p className={styles.note}>Approving or declining is recorded with the date in History.</p>
        </div>
      </div>
    </>
  );
}

function DeclineConfirm({ grant, onClose, onDeclined }: { grant: GrantRow; onClose: () => void; onDeclined: () => void }) {
  const [problem, setProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const question = useRef<HTMLHeadingElement>(null);
  const questionId = useId();

  // The question is the first thing a keyboard or screen reader user needs when it opens.
  useEffect(() => {
    question.current?.focus();
  }, []);

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
    <section aria-labelledby={questionId} className={styles.confirm}>
      <h2 id={questionId} ref={question} tabIndex={-1} className={styles.confirmTitle}>
        Decline this grant?
      </h2>
      <p className={styles.text}>
        <b>{`${SCOPE_WORD[grant.scope]} grant of ${grant.organisation}`}</b>
      </p>
      <p className={styles.text}>{`${grant.organisation} will not appear on the network board until a grant is approved.`}</p>
      {problem !== null ? (
        <p role="alert" className={styles.problem}>
          {problem}
        </p>
      ) : null}
      <div className={styles.actions}>
        <Button variant="secondary" busy={busy} dataEl="NADM-GRANT-DECLINE-CONFIRM-BTN" onClick={() => void decline()}>
          Decline
        </Button>
        <Button variant="neutral" onClick={onClose} dataEl="SCREENS-BOARD-CANCEL-BTN">
          Cancel
        </Button>
      </div>
    </section>
  );
}
