'use client';

import { useRef, useState } from 'react';
import { Button } from '@/components/ui/Button';
import { adminSend, useAdminRead, useSubmitKey } from '@/lib/tenantAdmin/browser';
import { TEAM_WORDS } from '@/lib/operator/funnel';
import { Avatar } from './Avatar';
import { PersonLookup, type Person } from './PersonLookup';
import styles from './People.module.css';

// People and roles (DEC-1317): the groups Overwatch made in the organisation's own directory, as one row per role
// that says who has it at a glance. A row opens (one at a time, so the page does not grow) to show the people in
// the role and, behind an Add button, a search to add someone. Each level shows only what the person asked for: the
// rows say who has a role, an open role lists its people, and the search and the group's directory name appear only
// when asked for, so an open role stays short. The directory holds the membership: this page reads it when it opens and
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

type Group = GroupsView['groups'][number];
type Member = Group['members'][number];

const ROLE_WORD: Record<string, string> = {
  'tenant-admin': 'Administrators',
  advisor: 'Advisor',
  clinical: 'Clinical lead',
  lead: 'Shift lead',
  owner: 'Criteria owner',
  exec: 'Planning',
  audit: 'Audit',
};
const ROLE_ABOUT: Record<string, string> = {
  'tenant-admin': 'Run Overwatch for your organisation: people, settings and contacts.',
  ...Object.fromEntries(TEAM_WORDS.map(([code, , about]) => [code, about])),
};

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

function nameOf(member: Member): string {
  return member.displayName ?? member.mail ?? 'Unnamed person';
}

function peopleWord(count: number): string {
  return count === 0 ? 'No one yet' : count === 1 ? '1 person' : `${count} people`;
}

/** "Jane Sample, Sam Second and 2 more": who is in the role, said in the row without opening it. */
function whoWord(members: readonly Member[]): string {
  if (members.length === 0) return 'Open to add the first person.';
  const names = members.slice(0, 3).map(nameOf);
  const rest = members.length - names.length;
  return rest > 0 ? `${names.join(', ')} and ${rest} more` : names.length > 1 ? `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}` : names[0]!;
}

export function GroupMembers() {
  const { state, reload } = useAdminRead<GroupsView>('/api/bff/tenant/groups');
  const [openId, setOpenId] = useState<string | null>(null);
  return (
    <section className={styles.people} aria-labelledby="people-heading">
      <h2 id="people-heading" className={styles.peopleTitle}>
        People and roles
      </h2>
      <p className={styles.peopleLede}>Open a role to see who has it and to add people. Changes reach your directory straight away.</p>
      {state.status === 'loading' ? <p className={styles.note}>Loading the groups.</p> : null}
      {state.status === 'failed' ? (
        <p role="alert" className={styles.problem}>
          We could not load the groups.
        </p>
      ) : null}
      {state.status === 'ok' && !state.data.setUp ? (
        <p className={styles.note}>Your organisation’s groups have not been set up yet. The platform operator does this once your administrator has approved Overwatch.</p>
      ) : null}
      {state.status === 'ok' && state.data.setUp && state.data.groups.length === 0 ? <p className={styles.note}>No groups are managed here yet.</p> : null}
      {state.status === 'ok' && state.data.groups.length > 0 ? (
        <ul className={styles.roles}>
          {state.data.groups.map((group) => (
            <li key={group.groupId}>
              <RoleRow group={group} open={openId === group.groupId} onToggle={() => setOpenId((now) => (now === group.groupId ? null : group.groupId))} onChanged={reload} />
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}

function RoleRow({ group, open, onToggle, onChanged }: { group: Group; open: boolean; onToggle: () => void; onChanged: () => void }) {
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirming, setConfirming] = useState<string | null>(null);
  const [justAdded, setJustAdded] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const row = useRef<HTMLElement>(null);
  const submitKey = useSubmitKey();
  const word = ROLE_WORD[group.role] ?? group.role;
  const title = `${word} group`;
  const panelId = `role-panel-${group.groupId}`;

  async function add(person: Person) {
    if (busy || person.mail === null) return;
    setMessage(null);
    setBusy(true);
    const result = await adminSend<{ changed: boolean }>('POST', `/api/bff/tenant/groups/${group.groupId}/members`, { email: person.mail }, submitKey.key());
    setBusy(false);
    submitKey.fresh();
    if (result.ok) {
      setJustAdded(person.userId);
      setAdding(false);
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
      <section className={styles.role} aria-label={title}>
        <div className={styles.roleHead}>
          <span className={styles.roleText}>
            <span className={styles.roleName}>{word}</span>
          </span>
        </div>
        <p role="alert" className={styles.problem}>
          This group is no longer in your directory. Ask the platform operator to set the groups up again.
        </p>
      </section>
    );
  }

  const memberIds = new Set(group.members.map((member) => member.userId));
  return (
    <section ref={row} className={styles.role} data-open={open} aria-label={title}>
      <button
        type="button"
        className={styles.roleHead}
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => {
          onToggle();
          // An opened role is brought fully into view, so it never opens below the fold.
          if (!open) requestAnimationFrame(() => row.current?.scrollIntoView?.({ block: 'nearest', behavior: 'smooth' }));
        }}
      >
        <span className={styles.roleText}>
          <span className={styles.roleName}>{word}</span>
          <span className={styles.roleAbout}>{ROLE_ABOUT[group.role] ?? ''}</span>
          <span className={styles.roleWho}>{whoWord(group.members)}</span>
        </span>
        <span className={styles.roleSide}>
          <span className={styles.stack} aria-hidden="true">
            {group.members.slice(0, 4).map((member) => (
              <Avatar key={member.userId} id={member.userId} name={member.displayName} mail={member.mail} size="sm" />
            ))}
          </span>
          <span className={styles.count}>{peopleWord(group.members.length)}</span>
          <svg className={styles.chevron} viewBox="0 0 20 20" width="18" height="18" aria-hidden="true" focusable="false">
            <path d="M5 8l5 5 5-5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </span>
      </button>
      <div id={panelId} className={styles.panel} data-open={open} inert={!open}>
        <div className={styles.panelInner}>
          <div className={styles.panelBody}>
            {group.members.length === 0 ? (
              <p className={styles.empty}>No one is in this group.</p>
            ) : (
              <ul className={styles.members} aria-label={`Members of the ${title.toLowerCase()}`}>
                {group.members.map((member) => {
                  const who = nameOf(member);
                  return (
                    <li key={member.userId} className={`${styles.member} ${justAdded === member.userId ? styles.memberNew : ''}`}>
                      <Avatar id={member.userId} name={member.displayName} mail={member.mail} />
                      <span className={styles.memberText}>
                        <span className={styles.memberName}>{member.displayName ?? '—'}</span>
                        <span className={styles.memberMail}>{member.mail ?? '—'}</span>
                      </span>
                      {confirming === member.userId ? (
                        <span className={styles.confirm}>
                          <Button variant="primary" busy={busy} onClick={() => void remove(member.userId)}>
                            Yes, remove<span className={styles.srOnly}>{` ${who} from the ${title.toLowerCase()}`}</span>
                          </Button>
                          <Button variant="neutral" onClick={() => setConfirming(null)}>
                            Cancel<span className={styles.srOnly}>{` removing ${who}`}</span>
                          </Button>
                        </span>
                      ) : (
                        <Button variant="neutral" busy={busy} onClick={() => setConfirming(member.userId)}>
                          Remove<span className={styles.srOnly}>{` ${who} from the ${title.toLowerCase()}`}</span>
                        </Button>
                      )}
                    </li>
                  );
                })}
              </ul>
            )}
            <div className={styles.tools}>
              <Button variant="secondary" onClick={() => setAdding((now) => !now)}>
                {adding ? 'Close search' : 'Add someone'}
                <span className={styles.srOnly}>{` to the ${title.toLowerCase()}`}</span>
              </Button>
              <details className={styles.details}>
                <summary>Details</summary>
                <p className={styles.note}>
                  Group name <strong>{group.name}</strong>
                </p>
              </details>
            </div>
            {open && adding ? (
              <div className={styles.lookupSlot}>
                <PersonLookup label="Search your directory" memberIds={memberIds} busy={busy} onPick={(person) => void add(person)} />
              </div>
            ) : null}
            {message !== null ? (
              <p role={message.ok ? 'status' : 'alert'} className={message.ok ? styles.ok : styles.problem}>
                {message.text}
              </p>
            ) : null}
          </div>
        </div>
      </div>
    </section>
  );
}
