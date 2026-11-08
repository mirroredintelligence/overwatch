'use client';

import { useEffect, useId, useRef, useState, type FormEvent, type ReactNode } from 'react';
import { TextField } from '@/components/forms/TextField';
import { Button } from '@/components/ui/Button';
import { Dialog } from '@/components/ui/Dialog';
import { StatusTag, type StatusTagVariant } from '@/components/ui/StatusTag';
import { BASE, post, useAdminRead, useNotice, type OverviewRead } from '@/lib/networkAdmin/browser';
import { AGREEMENT_REFERENCE, ORGANISATION_CODE } from '@/lib/networkAdmin/patterns';
import { dateText, MEMBER_STATUS_WORD, SCOPE_WORD } from '@/lib/networkAdmin/words';
import { SCOPES, type HealthRow, type MemberRow, type MemberStatus } from '@/lib/networkAdmin/views';
import { OwnedNetworkGate } from './OwnedNetworkGate';
import styles from './NetworkMembers.module.css';

// The network administrator's first page (TEN-080, design N1: NetworkMembers, NetworkMemberAdd, NetworkMemberEnd,
// NetworkAgreement, NetworkHealth; board NAdmin). The owner sees who has joined, what each organisation agreed to
// share and whether it is arriving, and never another organisation's private data. Nothing here is a tenant's id:
// an organisation is its name and a handle only the registry knows. Adding an organisation and recording an
// agreement open in place, beside the table; ending a membership asks first, in a dialog.

export const OWNER_LINE =
  "You see who has joined, what each organisation agreed to share and whether it is arriving. You never see another organisation's private data.";
const ADD_FAILED = 'We could not add that organisation. Check the code with them.';
const ADD_NOTE = `If the code is wrong, ineligible or already invited, the answer is the same: "${ADD_FAILED}"`;
const END_STAYS = "Its sharing stops now. What it already shared stays in the history, marked with today's date.";

const MEMBER_TAG: Readonly<Record<MemberStatus, StatusTagVariant>> = { active: 'live', invited: 'todo', left: 'closed', removed: 'closed' };

export function NetworkMembers() {
  return (
    <main className={styles.page}>
      <h1 className={styles.title}>Network members</h1>
      <p className={styles.lede}>{OWNER_LINE}</p>
      <OwnedNetworkGate>{(query) => <Members query={query} />}</OwnedNetworkGate>
    </main>
  );
}

function Members({ query }: { query: string }) {
  const { state, reload } = useAdminRead<OverviewRead>(`${BASE}${query}`);
  const { notice, say } = useNotice();
  const [adding, setAdding] = useState(false);
  const [ending, setEnding] = useState<MemberRow | null>(null);
  const addOpener = useRef<HTMLElement | null>(null);

  if (state.status === 'loading') return <p className={styles.muted}>Loading the members.</p>;
  if (state.status === 'failed') {
    return (
      <p role="alert" className={styles.problem}>
        We could not load the network members.
      </p>
    );
  }
  const { network } = state.data;

  function closeAdd() {
    setAdding(false);
    addOpener.current?.focus();
  }

  return (
    <>
      {notice !== null ? (
        <p role={notice.ok ? 'status' : 'alert'} className={notice.ok ? styles.ok : styles.problem}>
          {notice.text}
        </p>
      ) : null}
      <div className={styles.columns}>
        <div className={styles.column}>
          <Panel
            heading="Members"
            action={
              <Button
                variant="primary"
                dataEl="NADM-MEMBER-ADD-BTN"
                onClick={(event) => {
                  addOpener.current = event.currentTarget;
                  setAdding(true);
                }}
              >
                Add an organisation
              </Button>
            }
          >
            <div className={styles.scroll}>
              <table className={styles.table} data-el="NADM-MEMBERS-TABLE">
                <caption className={styles.srOnly}>Members</caption>
                <thead>
                  <tr>
                    <th scope="col">Organisation</th>
                    <th scope="col">Status</th>
                    <th scope="col">Joined</th>
                    <th scope="col">Agreement</th>
                    <th scope="col">
                      <span className={styles.srOnly}>Action</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {network.members.length === 0 ? (
                    <tr>
                      <td colSpan={5}>
                        Nothing here yet.
                        <span className={styles.muted}>{' Add an organisation with its organisation code, using the button above.'}</span>
                      </td>
                    </tr>
                  ) : (
                    network.members.map((member) => (
                      <tr key={member.id} data-row-ref={member.id}>
                        <td>
                          {member.organisation}
                          {member.role === 'owner' ? (
                            <>
                              {' '}
                              <span className={styles.owner}>(owner)</span>
                            </>
                          ) : null}
                        </td>
                        <td>
                          <StatusTag variant={MEMBER_TAG[member.status]}>{MEMBER_STATUS_WORD[member.status]}</StatusTag>
                        </td>
                        <td>{member.joinedAt === null && member.status === 'invited' ? 'Not yet' : dateText(member.joinedAt)}</td>
                        <td>
                          {member.acceptedAgreementVersion === null ? 'none' : `v${member.acceptedAgreementVersion}`}
                          {member.agreementBehind && network.agreementVersion !== null ? (
                            <span className={styles.behind}>{`Behind v${network.agreementVersion}`}</span>
                          ) : null}
                        </td>
                        <td>
                          {member.leftAt !== null ? <span className={styles.muted}>{`Left ${dateText(member.leftAt)}`}</span> : null}
                          {member.role === 'member' && (member.status === 'active' || member.status === 'invited') ? (
                            <Button variant="secondary" dataEl="NADM-MEMBER-END-BTN" onClick={() => setEnding(member)}>
                              End{' '}<span className={styles.srOnly}>{`membership of ${member.organisation}`}</span>
                            </Button>
                          ) : null}
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </Panel>

          <Panel heading="Health">
            <p className={styles.muted}>States and dates only. What an organisation shares is never shown here.</p>
            <div className={styles.scroll}>
              <table className={styles.table} data-el="NADM-HEALTH-TABLE">
                <caption className={styles.srOnly}>Sharing by organisation</caption>
                <thead>
                  <tr>
                    <th scope="col">Organisation</th>
                    {SCOPES.map((scope) => (
                      <th key={scope} scope="col">
                        {SCOPE_WORD[scope]}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {network.health.length === 0 ? (
                    <tr>
                      <td colSpan={4}>Nothing here yet.</td>
                    </tr>
                  ) : (
                    network.health.map((row) => (
                      <tr key={row.id} data-row-ref={row.id}>
                        <td>{row.organisation}</td>
                        {SCOPES.map((scope) => (
                          <td key={scope}>{sharingCell(row, scope)}</td>
                        ))}
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </Panel>

          <p className={styles.muted}>
            <a className={styles.link} data-el="NADM-HISTORY-LINK" href="/network-admin/history">
              History
            </a>
          </p>
        </div>

        <div className={styles.column}>
          {adding ? (
            <AddPanel
              query={query}
              onClose={closeAdd}
              onSent={() => {
                closeAdd();
                say(true, 'Invitation sent.');
                reload();
              }}
            />
          ) : null}

          <AgreementCard
            query={query}
            reference={network.agreementReference}
            version={network.agreementVersion}
            onRecorded={(version) => {
              say(true, `Agreement version ${version} recorded. Members show as behind until they accept it.`);
              reload();
            }}
          />

          <Panel heading="Ending a membership" dashed>
            <p className={styles.text}>{END_STAYS}</p>
          </Panel>
        </div>
      </div>

      {ending !== null ? (
        <EndDialog
          member={ending}
          query={query}
          onClose={() => setEnding(null)}
          onEnded={() => {
            setEnding(null);
            say(true, 'Membership ended.');
            reload();
          }}
        />
      ) : null}
    </>
  );
}

function Panel({ heading, action, dashed = false, children }: { heading: string; action?: ReactNode; dashed?: boolean; children: ReactNode }) {
  const id = useId();
  return (
    <section aria-labelledby={id} className={dashed ? `${styles.card} ${styles.dashed}` : styles.card}>
      <header className={styles.cardHead}>
        <h2 id={id} className={styles.heading}>
          {heading}
        </h2>
        {action}
      </header>
      {children}
    </section>
  );
}

function AddPanel({ query, onClose, onSent }: { query: string; onClose: () => void; onSent: () => void }) {
  const id = useId();
  const panel = useRef<HTMLElement>(null);
  const [code, setCode] = useState('');
  const [problem, setProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    panel.current?.querySelector('input')?.focus();
  }, []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    const wanted = code.trim();
    if (!ORGANISATION_CODE.test(wanted)) {
      setProblem(ADD_FAILED);
      return;
    }
    setProblem(null);
    setBusy(true);
    const result = await post(`${BASE}/members`, query, { organisationCode: wanted });
    setBusy(false);
    if (result.ok) onSent();
    // An unknown, an ineligible and an already invited organisation are one answer, so no list can be built.
    else setProblem(result.status === 404 || result.status === 400 || result.status === 409 ? ADD_FAILED : 'The invitation could not be sent. Try again.');
  }

  return (
    <section ref={panel} aria-labelledby={id} className={`${styles.card} ${styles.addCard}`}>
      <h2 id={id} className={styles.heading}>
        Add an organisation
      </h2>
      <form className={styles.stack} onSubmit={submit} noValidate>
        <TextField
          id="organisation-code"
          label="Organisation code"
          value={code}
          onChange={setCode}
          requirement="none"
          hint="The code is on the organisation's administration page."
          autoComplete="off"
          dataEl="NADM-MEMBER-CODE-INPUT"
        />
        <p className={styles.note}>{ADD_NOTE}</p>
        {problem !== null ? (
          <p role="alert" className={styles.problem}>
            {problem}
          </p>
        ) : null}
        <div className={styles.actions}>
          <Button variant="primary" type="submit" busy={busy} dataEl="NADM-MEMBER-SEND-BTN">
            Send invitation
          </Button>
          <Button variant="neutral" onClick={onClose} dataEl="SCREENS-BOARD-CANCEL-BTN">
            Cancel
          </Button>
        </div>
      </form>
    </section>
  );
}

function EndDialog({ member, query, onClose, onEnded }: { member: MemberRow; query: string; onClose: () => void; onEnded: () => void }) {
  const [problem, setProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function end() {
    if (busy) return;
    setBusy(true);
    setProblem(null);
    const result = await post(`${BASE}/members/${encodeURIComponent(member.id)}/remove`, query);
    setBusy(false);
    if (result.ok) onEnded();
    else setProblem('The membership could not be ended. Try again.');
  }

  return (
    <Dialog title={`End membership for ${member.organisation}?`} onClose={onClose}>
      <p className={styles.text}>{END_STAYS}</p>
      {problem !== null ? (
        <p role="alert" className={styles.problem}>
          {problem}
        </p>
      ) : null}
      <div className={styles.actions}>
        <Button variant="primary" busy={busy} onClick={() => void end()} dataEl="NADM-MEMBER-END-CONFIRM-BTN">
          End membership
        </Button>
        <Button variant="neutral" onClick={onClose} dataEl="SCREENS-BOARD-CANCEL-BTN">
          Cancel
        </Button>
      </div>
    </Dialog>
  );
}

const REFERENCE_PROBLEM = 'Enter the reference as it is in your document system, with letters, digits, dots, slashes and hyphens only.';
const VERSION_PROBLEM = 'Enter the version as a whole number, one or more.';

function AgreementCard({
  query,
  reference,
  version,
  onRecorded,
}: {
  query: string;
  reference: string | null;
  version: number | null;
  onRecorded: (version: number) => void;
}) {
  const id = useId();
  const [recording, setRecording] = useState(false);
  const [ref, setRef] = useState('');
  const [ver, setVer] = useState('');
  const [errors, setErrors] = useState<{ reference?: string; version?: string }>({});
  const [problem, setProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const opener = useRef<HTMLDivElement>(null);
  const form = useRef<HTMLFormElement>(null);
  // Set when the form closes, so focus goes back to the button that opened it once that button is rendered again.
  const returnFocus = useRef(false);

  useEffect(() => {
    if (recording) form.current?.querySelector('input')?.focus();
    else if (returnFocus.current) {
      returnFocus.current = false;
      opener.current?.querySelector('button')?.focus();
    }
  }, [recording]);

  function closeForm() {
    returnFocus.current = true;
    setErrors({});
    setProblem(null);
    setRecording(false);
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    const next: { reference?: string; version?: string } = {};
    const number = /^\d{1,6}$/.test(ver.trim()) ? Number(ver.trim()) : 0;
    if (!AGREEMENT_REFERENCE.test(ref.trim())) next.reference = REFERENCE_PROBLEM;
    if (number < 1) next.version = VERSION_PROBLEM;
    setErrors(next);
    setProblem(null);
    if (next.reference !== undefined || next.version !== undefined) return;
    setBusy(true);
    const result = await post(`${BASE}/agreement`, query, { reference: ref.trim(), version: number });
    setBusy(false);
    if (result.ok) {
      setRef('');
      setVer('');
      closeForm();
      onRecorded(number);
    } else {
      setProblem(result.status === 409 ? 'That version is not newer than the one in force.' : 'The agreement could not be recorded. Try again.');
    }
  }

  return (
    <section aria-labelledby={id} className={styles.card}>
      <h2 id={id} className={styles.heading}>
        Agreement
      </h2>
      <p className={styles.text}>
        {reference === null || version === null ? (
          'No agreement is recorded yet.'
        ) : (
          <>
            Current: <strong>{`${reference}, version ${version}`}</strong>.
          </>
        )}{' '}
        <span className={styles.muted}>Only the reference and version are stored, never the agreement itself.</span>
      </p>
      {recording ? (
        <form ref={form} className={styles.stack} onSubmit={submit} noValidate aria-label="Record an agreement">
          <TextField
            id="agreement-reference"
            label="Agreement reference"
            value={ref}
            onChange={setRef}
            requirement="none"
            error={errors.reference ?? null}
            autoComplete="off"
            dataEl="NADM-AGREEMENT-REFERENCE-INPUT"
          />
          <TextField
            id="agreement-version"
            label="Version"
            value={ver}
            onChange={setVer}
            requirement="none"
            inputMode="numeric"
            error={errors.version ?? null}
            autoComplete="off"
            dataEl="NADM-AGREEMENT-VERSION-INPUT"
          />
          {problem !== null ? (
            <p role="alert" className={styles.problem}>
              {problem}
            </p>
          ) : null}
          <div className={styles.actions}>
            <Button variant="primary" type="submit" busy={busy} dataEl="NADM-AGREEMENT-RECORD-BTN">
              Record agreement
            </Button>
            <Button variant="neutral" onClick={closeForm} dataEl="NADM-AGREEMENT-CANCEL-BTN">
              Cancel
            </Button>
          </div>
        </form>
      ) : (
        <div ref={opener} className={styles.actions}>
          <Button variant="secondary" dataEl="NADM-AGREEMENT-OPEN-BTN" onClick={() => setRecording(true)}>
            Record a new agreement
          </Button>
        </div>
      )}
    </section>
  );
}

function sharingCell(row: HealthRow, scope: (typeof SCOPES)[number]): ReactNode {
  const kind = row.kinds.find((k) => k.kind === scope);
  if (kind === undefined) return <StatusTag variant="paused">Not sharing</StatusTag>;
  return kind.status === 'active' ? (
    <StatusTag variant="live">Sharing</StatusTag>
  ) : (
    <StatusTag variant="closed">{`Ended on ${dateText(kind.endedAt)}`}</StatusTag>
  );
}
