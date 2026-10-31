'use client';

import { useState, type FormEvent } from 'react';
import { TextField } from '@/components/forms/TextField';
import { Button } from '@/components/ui/Button';
import { Card } from '@/components/ui/Card';
import { Dialog } from '@/components/ui/Dialog';
import { BASE, post, useAdminRead, useNotice, type OverviewRead } from '@/lib/networkAdmin/browser';
import { AGREEMENT_REFERENCE, ORGANISATION_CODE } from '@/lib/networkAdmin/patterns';
import { dateText, MEMBER_STATUS_WORD, SCOPE_WORD } from '@/lib/networkAdmin/words';
import { SCOPES, type HealthRow, type MemberRow } from '@/lib/networkAdmin/views';
import styles from '../admin/admin.module.css';
import { OwnedNetworkGate } from './OwnedNetworkGate';

// The network administrator's first page (TEN-080, design N1: NetworkMembers, NetworkMemberAdd,
// NetworkMemberEnd, NetworkAgreement, NetworkHealth). The owner sees who has joined, what each organisation
// agreed to share and whether it is arriving, and never another organisation's private data. Nothing here is
// a tenant's id: an organisation is its name and a handle only the registry knows.

export const OWNER_LINE =
  "You see who has joined, what each organisation agreed to share and whether it is arriving. You never see another organisation's private data.";
const ADD_FAILED = 'We could not add that organisation. Check the code with them.';

export function NetworkMembers() {
  return (
    <main className={styles.page}>
      <h1 className={styles.title}>Network members</h1>
      <p className={styles.text}>{OWNER_LINE}</p>
      <OwnedNetworkGate>{(query) => <Members query={query} />}</OwnedNetworkGate>
    </main>
  );
}

function Members({ query }: { query: string }) {
  const { state, reload } = useAdminRead<OverviewRead>(`${BASE}${query}`);
  const { notice, say } = useNotice();
  const [adding, setAdding] = useState(false);
  const [ending, setEnding] = useState<MemberRow | null>(null);

  if (state.status === 'loading') return <p className={styles.muted}>Loading the members.</p>;
  if (state.status === 'failed') {
    return (
      <p role="alert" className={styles.problem}>
        We could not load the network members.
      </p>
    );
  }
  const { network } = state.data;
  return (
    <>
      {notice !== null ? (
        <p role={notice.ok ? 'status' : 'alert'} className={notice.ok ? styles.ok : styles.problem}>
          {notice.text}
        </p>
      ) : null}
      <Card heading="Members">
        <div className={styles.scroll}>
          <table className={styles.table} data-el="NADM-MEMBERS-TABLE">
            <caption>Members</caption>
            <thead>
              <tr>
                <th scope="col">Organisation</th>
                <th scope="col">Status</th>
                <th scope="col">Joined</th>
                <th scope="col">Left</th>
                <th scope="col">Agreement version accepted</th>
                <th scope="col">
                  <span className={styles.srOnly}>Action</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {network.members.length === 0 ? (
                <tr>
                  <td colSpan={6}>Nothing here yet.</td>
                </tr>
              ) : (
                network.members.map((member) => (
                  <tr key={member.id} data-row-ref={member.id}>
                    <td>
                      {member.organisation}
                      {member.role === 'owner' ? <span className={styles.tag}>Network owner</span> : null}
                    </td>
                    <td>
                      <span className={member.status === 'active' ? styles.tag : `${styles.tag} ${styles.tagDashed}`}>{MEMBER_STATUS_WORD[member.status]}</span>
                    </td>
                    <td>{dateText(member.joinedAt)}</td>
                    <td>{dateText(member.leftAt)}</td>
                    <td>
                      {member.acceptedAgreementVersion ?? '-'}
                      {member.agreementBehind && network.agreementVersion !== null ? (
                        <span className={styles.muted}>{` Agreement version ${network.agreementVersion} is available`}</span>
                      ) : null}
                    </td>
                    <td>
                      {member.role === 'member' && (member.status === 'active' || member.status === 'invited') ? (
                        <Button variant="neutral" dataEl="NADM-MEMBER-END-BTN" onClick={() => setEnding(member)}>
                          End membership<span className={styles.srOnly}>{` of ${member.organisation}`}</span>
                        </Button>
                      ) : null}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
        <div className={styles.actions}>
          <Button variant="primary" dataEl="NADM-MEMBER-ADD-BTN" onClick={() => setAdding(true)}>
            Add an organisation
          </Button>
        </div>
      </Card>

      <AgreementCard
        query={query}
        reference={network.agreementReference}
        version={network.agreementVersion}
        onRecorded={(version) => {
          say(true, `Agreement version ${version} recorded. Members show as behind until they accept it.`);
          reload();
        }}
      />

      <HealthCard health={network.health} />

      <p className={styles.text}>
        <a className={styles.link} data-el="NADM-HISTORY-LINK" href="/network-admin/history">
          History
        </a>
      </p>

      {adding ? (
        <AddDialog
          query={query}
          onClose={() => setAdding(false)}
          onSent={() => {
            setAdding(false);
            say(true, 'Invitation sent.');
            reload();
          }}
        />
      ) : null}
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

function AddDialog({ query, onClose, onSent }: { query: string; onClose: () => void; onSent: () => void }) {
  const [code, setCode] = useState('');
  const [problem, setProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

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
    <Dialog title="Add an organisation" onClose={onClose}>
      <form className={styles.stack} onSubmit={submit} noValidate aria-label="Add an organisation">
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
    </Dialog>
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
      <p className={styles.text}>Its sharing stops now. What it already shared stays in the history, marked with today&apos;s date.</p>
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
  const [ref, setRef] = useState('');
  const [ver, setVer] = useState('');
  const [errors, setErrors] = useState<{ reference?: string; version?: string }>({});
  const [problem, setProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

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
      onRecorded(number);
    } else {
      setProblem(result.status === 409 ? 'That version is not newer than the one in force.' : 'The agreement could not be recorded. Try again.');
    }
  }

  return (
    <Card heading="Agreement">
      <p className={styles.text}>{reference === null || version === null ? 'No agreement is recorded yet.' : `Agreement ${reference}, version ${version}.`}</p>
      <form className={styles.stack} onSubmit={submit} noValidate aria-label="Record an agreement">
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
        <p className={styles.muted}>Only the reference and version are stored, never the agreement itself.</p>
        {problem !== null ? (
          <p role="alert" className={styles.problem}>
            {problem}
          </p>
        ) : null}
        <div className={styles.actions}>
          <Button variant="primary" type="submit" busy={busy} dataEl="NADM-AGREEMENT-RECORD-BTN">
            Record agreement
          </Button>
        </div>
      </form>
    </Card>
  );
}

function sharingWord(row: HealthRow, scope: (typeof SCOPES)[number]): string {
  const kind = row.kinds.find((k) => k.kind === scope);
  if (kind === undefined) return 'Not sharing';
  return kind.status === 'active' ? 'Sharing' : `Ended on ${dateText(kind.endedAt)}`;
}

function HealthCard({ health }: { health: HealthRow[] }) {
  return (
    <Card heading="Health">
      <p className={styles.muted}>States and dates only. What an organisation shares is never shown here.</p>
      <div className={styles.scroll}>
        <table className={styles.table} data-el="NADM-HEALTH-TABLE">
          <caption>Sharing by organisation</caption>
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
            {health.length === 0 ? (
              <tr>
                <td colSpan={4}>Nothing here yet.</td>
              </tr>
            ) : (
              health.map((row) => (
                <tr key={row.id} data-row-ref={row.id}>
                  <td>{row.organisation}</td>
                  {SCOPES.map((scope) => (
                    <td key={scope}>{sharingWord(row, scope)}</td>
                  ))}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </Card>
  );
}
