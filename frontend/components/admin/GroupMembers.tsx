'use client';

import { useState, type FormEvent } from 'react';
import { TextField } from '@/components/forms/TextField';
import { Button } from '@/components/ui/Button';
import { Card } from '@/components/ui/Card';
import { adminSend, useAdminRead, useSubmitKey } from '@/lib/tenantAdmin/browser';
import styles from './admin.module.css';

// Groups and members (DEC-1317): the groups Overwatch made in the organisation's own directory, who is in each,
// and adding or removing a person. The directory holds the membership: this page reads it when it opens and
// Overwatch stores none of it. Which groups can be changed is decided at the back end (the groups it made, whose
// names start with the organisation's prefix), never by this page.

export type GroupsView = {
  setUp: boolean;
  groups: {
    groupId: string;
    name: string | null;
    role: string;
    missing: boolean;
    members: { userId: string; displayName: string | null; mail: string | null }[];
  }[];
};

const ROLE_WORD: Record<string, string> = {
  'tenant-admin': 'Administrators',
  advisor: 'Advisor',
  clinical: 'Clinical lead',
  lead: 'Shift lead',
  owner: 'Criteria owner',
  exec: 'Planning',
  audit: 'Audit',
};
const WORK_EMAIL = /^[A-Za-z0-9._%+'-]{1,64}@[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$/;

const ADD_FAILED: Record<number, string> = {
  400: 'No one in your directory has that address.',
  403: 'That group cannot be changed here.',
  404: 'That group cannot be changed here.',
  409: 'That change could not be made. The group may have been removed from your directory, or this is the last administrator, who cannot be removed.',
  503: 'The directory could not be reached. Try again in a minute.',
};

function failure(status: number): string {
  return ADD_FAILED[status] ?? 'That change could not be made. Try again.';
}

export function GroupMembers() {
  const { state, reload } = useAdminRead<GroupsView>('/api/bff/tenant/groups');
  return (
    <Card heading="Groups and members">
      <p className={styles.text}>
        These are the groups Overwatch made in your own directory. Whoever is in a group has its role when they sign in. Changes here are made in your directory straight away.
      </p>
      {state.status === 'loading' ? <p className={styles.muted}>Loading the groups.</p> : null}
      {state.status === 'failed' ? (
        <p role="alert" className={styles.problem}>
          We could not load the groups.
        </p>
      ) : null}
      {state.status === 'ok' && !state.data.setUp ? (
        <p className={styles.text}>Your organisation’s groups have not been set up yet. The platform operator does this once your administrator has approved Overwatch.</p>
      ) : null}
      {state.status === 'ok' && state.data.setUp && state.data.groups.length === 0 ? <p className={styles.text}>No groups are managed here yet.</p> : null}
      {state.status === 'ok'
        ? state.data.groups.map((group) => <GroupBlock key={group.groupId} group={group} onChanged={reload} />)
        : null}
    </Card>
  );
}

function GroupBlock({ group, onChanged }: { group: GroupsView['groups'][number]; onChanged: () => void }) {
  const [email, setEmail] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirming, setConfirming] = useState<string | null>(null);
  const submitKey = useSubmitKey();
  const word = ROLE_WORD[group.role] ?? group.role;
  const title = `${word} group`;

  async function add(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    setMessage(null);
    const address = email.trim();
    if (!WORK_EMAIL.test(address) || address.includes('..')) {
      setError('Enter the person’s work email address, for example name@organisation.nhs.uk.');
      return;
    }
    setError(null);
    setBusy(true);
    const result = await adminSend<{ changed: boolean }>('POST', `/api/bff/tenant/groups/${group.groupId}/members`, { email: address }, submitKey.key());
    setBusy(false);
    if (result.ok) {
      submitKey.fresh();
      setEmail('');
      setMessage({ ok: true, text: result.data.changed ? 'Added to the group.' : 'That person is already in the group.' });
      onChanged();
    } else setMessage({ ok: false, text: failure(result.status) });
  }

  async function remove(userId: string) {
    if (busy) return;
    setBusy(true);
    setMessage(null);
    const result = await adminSend<{ changed: boolean }>('DELETE', `/api/bff/tenant/groups/${group.groupId}/members/${userId}`, undefined, submitKey.key());
    setBusy(false);
    submitKey.fresh();
    setConfirming(null);
    if (result.ok) {
      setMessage({ ok: true, text: result.data.changed ? 'Removed from the group.' : 'That person was not in the group.' });
      onChanged();
    } else setMessage({ ok: false, text: failure(result.status) });
  }

  if (group.missing) {
    return (
      <Card heading={title} headingLevel={3}>
        <p role="alert" className={styles.problem}>
          This group is no longer in your directory. Ask the platform operator to set the groups up again.
        </p>
      </Card>
    );
  }

  return (
    <Card heading={title} headingLevel={3}>
      <p className={styles.text}>
        Group name <strong>{group.name}</strong>
      </p>
      <div className={styles.scroll}>
        <table className={styles.table}>
          <caption>{`Members of the ${title.toLowerCase()}`}</caption>
          <thead>
            <tr>
              <th scope="col">Name</th>
              <th scope="col">Email</th>
              <th scope="col">
                <span className={styles.srOnly}>Action</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {group.members.length === 0 ? (
              <tr>
                <td colSpan={3}>No one is in this group.</td>
              </tr>
            ) : (
              group.members.map((member) => {
                const who = member.displayName ?? member.mail ?? 'this person';
                return (
                  <tr key={member.userId}>
                    <td>{member.displayName ?? '—'}</td>
                    <td>{member.mail ?? '—'}</td>
                    <td>
                      {confirming === member.userId ? (
                        <div className={styles.actions}>
                          <Button variant="primary" busy={busy} onClick={() => void remove(member.userId)}>
                            Yes, remove<span className={styles.srOnly}>{` ${who} from the ${title.toLowerCase()}`}</span>
                          </Button>
                          <Button variant="neutral" onClick={() => setConfirming(null)}>
                            Cancel<span className={styles.srOnly}>{` removing ${who}`}</span>
                          </Button>
                        </div>
                      ) : (
                        <Button variant="neutral" busy={busy} onClick={() => setConfirming(member.userId)}>
                          Remove<span className={styles.srOnly}>{` ${who} from the ${title.toLowerCase()}`}</span>
                        </Button>
                      )}
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
      <form className={styles.stack} onSubmit={(event) => void add(event)} noValidate aria-label={`Add a person to the ${title.toLowerCase()}`}>
        <TextField
          id={`member-email-${group.groupId}`}
          label={`Work email of the person to add to the ${title.toLowerCase()}`}
          value={email}
          onChange={(value) => {
            submitKey.fresh();
            setEmail(value);
          }}
          requirement="none"
          inputMode="email"
          autoComplete="off"
          error={error}
        />
        {message !== null ? (
          <p role={message.ok ? 'status' : 'alert'} className={message.ok ? styles.ok : styles.problem}>
            {message.text}
          </p>
        ) : null}
        <div className={styles.actions}>
          <Button variant="primary" type="submit" busy={busy}>
            Add person<span className={styles.srOnly}>{` to the ${title.toLowerCase()}`}</span>
          </Button>
        </div>
      </form>
    </Card>
  );
}
