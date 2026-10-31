'use client';

import { useState, type FormEvent } from 'react';
import { TextField } from '@/components/forms/TextField';
import { Button } from '@/components/ui/Button';
import { Card } from '@/components/ui/Card';
import { adminSend, useAdminRead, useSubmitKey } from '@/lib/tenantAdmin/browser';
import { MAPPABLE_ROLE_WORDS } from '@/lib/tenantAdmin/roles';
import type { Overview } from './AdminOverview';
import { whenText } from '@/lib/tenantAdmin/words';
import styles from './admin.module.css';

// Users and roles (TEN-076): the directory the organisation signs in with and which of its groups gets which
// role. A directory is bound as pending and stays so until the platform operator verifies it; a group is
// never mapped to the administrator role (the first administrator is invited by the platform operator).

const GUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const DIRECTORY_WORD = { pending: 'Pending', verified: 'Verified', revoked: 'Revoked' } as const;
const MAPPING_WORD = { active: 'In use', retired: 'Stopped' } as const;

export function UsersAndRoles() {
  const { state, reload } = useAdminRead<Overview>('/api/bff/tenant/overview');
  return (
    <main className={styles.page}>
      <h1 className={styles.title}>Users and roles</h1>
      {state.status === 'loading' ? <p className={styles.muted}>Loading the directory and roles.</p> : null}
      {state.status === 'failed' ? (
        <p role="alert" className={styles.problem}>
          We could not load the directory and roles.
        </p>
      ) : null}
      {state.status === 'ok' ? (
        <>
          <DirectoryCard bindings={state.data.bindings} onSaved={reload} />
          <MappingCard mappings={state.data.mappings} onSaved={reload} />
        </>
      ) : null}
    </main>
  );
}

function DirectoryCard({ bindings, onSaved }: { bindings: Overview['bindings']; onSaved: () => void }) {
  const [id, setId] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const submitKey = useSubmitKey();

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    setMessage(null);
    if (!GUID.test(id.trim())) {
      setError('Enter the directory id as it is shown in your directory, for example 00000000-0000-0000-0000-000000000000.');
      return;
    }
    setError(null);
    setBusy(true);
    const result = await adminSend('PUT', '/api/bff/tenant/directory', { directoryId: id.trim() }, submitKey.key());
    setBusy(false);
    if (result.ok) {
      submitKey.fresh();
      setId('');
      setMessage({ ok: true, text: 'Directory saved. It stays pending until the platform operator verifies it.' });
      onSaved();
    } else setMessage({ ok: false, text: 'The directory could not be saved. Try again.' });
  }

  return (
    <Card heading="Directory">
      <p className={styles.text}>People sign in with the directory your organisation has bound. The platform operator verifies it before anyone can use it.</p>
      <div className={styles.scroll}>
        <table className={styles.table}>
          <caption>Directories</caption>
          <thead>
            <tr>
              <th scope="col">Directory id</th>
              <th scope="col">State</th>
              <th scope="col">Verified</th>
            </tr>
          </thead>
          <tbody>
            {bindings.length === 0 ? (
              <tr>
                <td colSpan={3}>No directory is bound yet.</td>
              </tr>
            ) : (
              bindings.map((b) => (
                <tr key={b.directoryId}>
                  <td>{b.directoryId}</td>
                  <td>
                    <span className={b.status === 'verified' ? styles.tag : `${styles.tag} ${styles.tagDashed}`}>{DIRECTORY_WORD[b.status]}</span>
                  </td>
                  <td>{whenText(b.verifiedAt)}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
      <form className={styles.stack} onSubmit={submit} noValidate aria-label="Bind a directory">
        <TextField
          id="directory-id"
          label="Directory id"
          value={id}
          onChange={(value) => {
            submitKey.fresh();
            setId(value);
          }}
          requirement="none"
          error={error}
          autoComplete="off"
        />
        {message !== null ? (
          <p role={message.ok ? 'status' : 'alert'} className={message.ok ? styles.ok : styles.problem}>
            {message.text}
          </p>
        ) : null}
        <div className={styles.actions}>
          <Button variant="primary" type="submit" busy={busy} dataEl="ADMIN-DIRECTORY-BTN">
            Bind directory
          </Button>
        </div>
      </form>
    </Card>
  );
}

function MappingCard({ mappings, onSaved }: { mappings: Overview['mappings']; onSaved: () => void }) {
  const [group, setGroup] = useState('');
  const [role, setRole] = useState<string>(MAPPABLE_ROLE_WORDS[0]![0]);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const submitKey = useSubmitKey();

  async function send(body: { groupObjectId: string; role: string; status: 'active' | 'retired' }, done: string) {
    if (busy) return;
    setBusy(true);
    setMessage(null);
    const result = await adminSend('PUT', '/api/bff/tenant/role-mappings', body, submitKey.key());
    setBusy(false);
    submitKey.fresh();
    if (result.ok) {
      setMessage({ ok: true, text: done });
      onSaved();
    } else setMessage({ ok: false, text: 'The mapping could not be saved. Try again.' });
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (group.trim() === '') {
      setError('Enter the group id.');
      return;
    }
    setError(null);
    void send({ groupObjectId: group.trim(), role, status: 'active' }, 'Group mapped.').then(() => setGroup(''));
  }

  return (
    <Card heading="Role mappings">
      <p className={styles.text}>
        A group in your directory gives its members a role. The first administrator is invited by the platform operator, so a group cannot be mapped to the administrator role.
      </p>
      <div className={styles.scroll}>
        <table className={styles.table}>
          <caption>Role mappings</caption>
          <thead>
            <tr>
              <th scope="col">Group id</th>
              <th scope="col">Role</th>
              <th scope="col">State</th>
              <th scope="col">
                <span className={styles.srOnly}>Action</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {mappings.length === 0 ? (
              <tr>
                <td colSpan={4}>No group is mapped yet.</td>
              </tr>
            ) : (
              mappings.map((m) => (
                <tr key={`${m.groupObjectId}-${m.role}`}>
                  <td>{m.groupObjectId}</td>
                  <td>{MAPPABLE_ROLE_WORDS.find(([code]) => code === m.role)?.[1] ?? m.role}</td>
                  <td>
                    <span className={m.status === 'active' ? styles.tag : `${styles.tag} ${styles.tagDashed}`}>{MAPPING_WORD[m.status]}</span>
                  </td>
                  <td>
                    {m.status === 'active' ? (
                      <Button variant="neutral" busy={busy} onClick={() => void send({ groupObjectId: m.groupObjectId, role: m.role, status: 'retired' }, 'Mapping stopped.')}>
                        Stop using<span className={styles.srOnly}>{` the mapping for group ${m.groupObjectId}`}</span>
                      </Button>
                    ) : null}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
      <form className={styles.stack} onSubmit={submit} noValidate aria-label="Map a group">
        <TextField
          id="group-id"
          label="Group id"
          value={group}
          onChange={(value) => {
            submitKey.fresh();
            setGroup(value);
          }}
          requirement="none"
          error={error}
          autoComplete="off"
        />
        <div className={styles.selectLabel}>
          <label htmlFor="mapping-role">Role</label>
          <select id="mapping-role" className={styles.select} value={role} onChange={(event) => setRole(event.target.value)}>
            {MAPPABLE_ROLE_WORDS.map(([code, word]) => (
              <option key={code} value={code}>
                {word}
              </option>
            ))}
          </select>
        </div>
        {message !== null ? (
          <p role={message.ok ? 'status' : 'alert'} className={message.ok ? styles.ok : styles.problem}>
            {message.text}
          </p>
        ) : null}
        <div className={styles.actions}>
          <Button variant="primary" type="submit" busy={busy} dataEl="ADMIN-MAPPING-BTN">
            Map group
          </Button>
        </div>
      </form>
    </Card>
  );
}
