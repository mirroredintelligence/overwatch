'use client';

import Link from 'next/link';
import { useState } from 'react';
import { useAdminRead } from '@/lib/tenantAdmin/browser';
import type { parseOverview } from '@/lib/tenantAdmin/views';
import { Loading, SkeletonRows } from '@/components/ui/Skeleton';
import { StatusTag, type StatusTagVariant } from '@/components/ui/StatusTag';
import { Disclose } from './Disclose';
import styles from './AdminOverview.module.css';

// The administrator's first page (TEN-076), on board A1: what needs this person (the rows, most urgent first),
// the steps already done, and the organisation's facts, people and settings in force. Nothing here is a tenant
// id, a secret or a person's reference: the BFF has dropped them (lib/tenantAdmin/views.ts), and people are
// counted, never named.

export type Overview = ReturnType<typeof parseOverview>;

export const ADMIN_PAGES: readonly [string, string][] = [
  ['Settings and versions', '/admin/config'],
  ['Users and roles', '/admin/users'],
  ['Contacts', '/admin/contacts'],
  ['Email sender', '/admin/email'],
  ['Data retention', '/admin/retention'],
  ['Who has accessed your organisation', '/admin/access'],
  ['Support requests', '/admin/support'],
  ['Sharing with the network', '/admin/sharing'],
];

type Ticket = { id: string; state: string };
type ConfigVersion = { version: number; status: string; approvals: number; approvalsRequired: number; authoredByYou: boolean; approvedByYou: boolean; clinicalKeys: string[] };
type Group = { groupId: string; role: string; missing: boolean; members: { userId: string }[] };
type Data = { overview: Overview; tickets: Ticket[]; versions: ConfigVersion[]; groups: Group[] };

/** The four reads the page is made of. The page is whole when all four have answered, and failed when any has. */
function useOverviewData(): { state: 'loading' | 'failed' | 'ok'; data: Data | null; reload: () => void } {
  const overview = useAdminRead<Overview>('/api/bff/tenant/overview');
  const tickets = useAdminRead<{ tickets: Ticket[] }>('/api/bff/tenant/support-tickets');
  const versions = useAdminRead<{ versions: ConfigVersion[] }>('/api/bff/tenant/config/versions');
  const groups = useAdminRead<{ groups: Group[] }>('/api/bff/tenant/groups');
  const all = [overview.state, tickets.state, versions.state, groups.state];
  const state = all.some((s) => s.status === 'failed') ? 'failed' : all.some((s) => s.status === 'loading') ? 'loading' : 'ok';
  const data =
    overview.state.status === 'ok' && tickets.state.status === 'ok' && versions.state.status === 'ok' && groups.state.status === 'ok'
      ? { overview: overview.state.data, tickets: tickets.state.data.tickets, versions: versions.state.data.versions, groups: groups.state.data.groups }
      : null;
  return {
    state,
    data,
    reload: () => {
      overview.reload();
      tickets.reload();
      versions.reload();
      groups.reload();
    },
  };
}

export type Step = {
  key: 'directory' | 'group' | 'phone' | 'safety';
  done: boolean;
  waiting?: boolean;
  title: string;
  hint?: string;
  action?: { label: string; href: string };
};

/** What the organisation still has to do before people can sign in and the service can run, each step with its
 * state and, while it is to do, the page that does it. Done steps are kept too: they sit under "Done". */
export function setupSteps(overview: Overview): Step[] {
  const bound = overview.bindings.filter((b) => b.status !== 'revoked');
  const verified = bound.some((b) => b.status === 'verified');
  const waiting = bound.some((b) => b.status === 'pending');
  const groups = overview.mappings.filter((m) => m.status === 'active').length;
  const phone = overview.contacts.some((c) => c.kind === 'coordination-phone');
  const safety = overview.contacts.some((c) => c.kind === 'clinical-safety-officer');
  return [
    verified
      ? { key: 'directory', done: true, title: 'A directory is bound and verified.' }
      : waiting
        ? { key: 'directory', done: false, waiting: true, title: 'Your directory is waiting for the platform operator to verify it' }
        : {
            key: 'directory',
            done: false,
            title: 'Bind the directory your people sign in with',
            hint: 'People sign in with this directory.',
            action: { label: 'Bind directory', href: '/admin/users' },
          },
    groups > 0
      ? { key: 'group', done: true, title: 'A group is mapped to a role.' }
      : {
          key: 'group',
          done: false,
          title: 'Map a group to a role, so people can sign in',
          hint: 'Until one is, nobody can sign in except you.',
          action: { label: 'Map group', href: '/admin/users' },
        },
    phone
      ? { key: 'phone', done: true, title: 'The coordination phone is recorded.' }
      : {
          key: 'phone',
          done: false,
          title: 'Add the coordination phone',
          hint: 'Staff see it on any page that says who to phone.',
          action: { label: 'Add phone', href: '/admin/contacts' },
        },
    safety
      ? { key: 'safety', done: true, title: 'The clinical safety officer is recorded.' }
      : {
          key: 'safety',
          done: false,
          title: 'Add the clinical safety officer',
          hint: 'Recorded on the Contacts page.',
          action: { label: 'Add officer', href: '/admin/contacts' },
        },
  ];
}

type Task = {
  key: string;
  urgent?: boolean;
  tag: StatusTagVariant;
  tagWord: string;
  title: string;
  hint?: string;
  action?: { label: string; href: string; primary?: boolean };
};

/** The rows of "What needs you": a support request waiting, a version another person must approve, and the setup
 * steps still to do. A version this person wrote, or has already approved, is not theirs to act on. */
function tasksOf(data: Data): Task[] {
  const tasks: Task[] = [];
  const waiting = data.tickets.filter((t) => t.state === 'pending').length;
  if (waiting > 0) {
    tasks.push({
      key: 'support',
      urgent: true,
      tag: 'waiting',
      tagWord: 'Waiting for you',
      title: waiting === 1 ? 'A support person is asking to look into your organisation' : `${waiting} support people are asking to look into your organisation`,
      hint: 'Approve or refuse. Nothing opens until you give them the code.',
      action: { label: 'Review request', href: '/admin/support', primary: true },
    });
  }
  const version = data.versions.find((v) => v.status === 'pending-approval' && !v.authoredByYou && !v.approvedByYou);
  if (version !== undefined) {
    tasks.push({
      key: 'version',
      tag: 'todo',
      tagWord: 'To do',
      title: `Approve version ${version.version} of your settings`,
      hint: `${version.clinicalKeys.length > 0 ? 'It changes a clinical setting, so it needs' : 'It needs'} ${version.approvalsRequired} approvals from other people. ${version.approvals} given.`,
      action: { label: 'Open version', href: `/admin/config/${version.version}` },
    });
  }
  for (const step of setupSteps(data.overview)) {
    if (step.done) continue;
    tasks.push({
      key: step.key,
      tag: step.waiting === true ? 'waiting' : 'todo',
      tagWord: step.waiting === true ? 'Waiting' : 'To do',
      title: step.title,
      hint: step.hint,
      action: step.action,
    });
  }
  return tasks;
}

const dayText = new Intl.DateTimeFormat('en-GB', { timeZone: 'Europe/London', day: 'numeric', month: 'short', year: 'numeric' });

/** "21 Oct 2026" in London time, or a dash for no date. */
function dayOf(iso: string | null | undefined): string {
  if (iso === null || iso === undefined) return '-';
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? '-' : dayText.format(date);
}

function count(n: number, one: string, many: string): string {
  return `${n} ${n === 1 ? one : many}`;
}

export function AdminOverview() {
  const { state, data, reload } = useOverviewData();
  const [doneOpen, setDoneOpen] = useState(false);
  const tasks = data === null ? [] : tasksOf(data);
  const done = data === null ? [] : setupSteps(data.overview).filter((s) => s.done);
  const actionable = tasks.filter((t) => t.action !== undefined).length;

  return (
    <main className={styles.page}>
      <h1 className={styles.srOnly}>Administration</h1>

      <section aria-label="What needs you" className={styles.needs}>
        <div className={styles.headRow}>
          <h2 className={styles.heading}>What needs you</h2>
          {state === 'ok' && actionable > 0 ? <span className={styles.count}>{count(actionable, 'thing', 'things')}</span> : null}
        </div>

        {state === 'loading' ? (
          <Loading label="Loading your organisation.">
            <SkeletonRows count={3} />
          </Loading>
        ) : null}

        {state === 'failed' ? (
          <div role="alert" className={styles.problem}>
            <StatusTag variant="problem">Could not load</StatusTag>
            <p className={styles.text}>We could not load your organisation. Nothing has changed.</p>
            <button type="button" className={styles.secondary} onClick={reload}>
              Try again
            </button>
          </div>
        ) : null}

        {data !== null ? (
          <>
            {actionable === 0 ? (
              <div className={styles.allDone}>
                <p className={styles.allDoneTitle}>● All done</p>
                <p className={styles.text}>Nothing needs you. The list comes back when something does.</p>
              </div>
            ) : null}
            {tasks.length > 0 ? (
              <ul className={styles.list}>
                {tasks.map((task) => (
                  <TaskRow key={task.key} task={task} />
                ))}
              </ul>
            ) : null}
            {done.length > 0 ? (
              <Disclose
                open={doneOpen}
                onToggle={() => setDoneOpen((open) => !open)}
                title={
                  <>
                    Done <span className={styles.muted}>· {count(done.length, 'step', 'steps')}</span>
                  </>
                }
              >
                <ul className={styles.list}>
                  {done.map((step) => (
                    <li key={step.key} className={styles.text}>
                      {step.title}
                    </li>
                  ))}
                </ul>
              </Disclose>
            ) : null}
          </>
        ) : null}
      </section>

      {data !== null ? <Facts data={data} /> : null}
    </main>
  );
}

function TaskRow({ task }: { task: Task }) {
  return (
    <li className={task.urgent === true ? `${styles.task} ${styles.urgent}` : styles.task}>
      <StatusTag variant={task.tag}>{task.tagWord}</StatusTag>
      <div className={styles.taskText}>
        <p className={styles.taskTitle}>{task.title}</p>
        {task.hint !== undefined ? <p className={styles.taskHint}>{task.hint}</p> : null}
      </div>
      {task.action !== undefined ? (
        <Link className={task.action.primary === true ? styles.primary : styles.secondary} href={task.action.href}>
          {task.action.label}
        </Link>
      ) : null}
    </li>
  );
}

function Facts({ data }: { data: Data }) {
  const { tenant, config } = data.overview;
  const inUse = data.groups.filter((g) => !g.missing && g.members.length > 0);
  const roles = new Set(inUse.map((g) => g.role)).size;
  const people = new Set(inUse.flatMap((g) => g.members.map((m) => m.userId))).size;
  return (
    <aside aria-label="Your organisation" className={styles.aside}>
      <section className={styles.card} aria-label="Your organisation facts">
        <div className={styles.labelRow}>
          <span className={styles.label}>Your organisation</span>
          {tenant.status === 'provisioning' ? <StatusTag variant="waiting">Being set up</StatusTag> : null}
        </div>
        <p className={styles.orgName}>{tenant.displayName}</p>
        <dl className={styles.facts}>
          <dt>ODS code</dt>
          <dd>{tenant.odsCode ?? '-'}</dd>
          <dt>Time zone</dt>
          <dd>{tenant.timeZone}</dd>
          <dt>Status</dt>
          <dd>{tenant.status}</dd>
          <dt>Address</dt>
          <dd>{tenant.host ?? '-'}</dd>
        </dl>
        {tenant.status === 'provisioning' ? <p className={styles.text}>Going live is done by the platform team once everything here is finished.</p> : null}
      </section>

      <section className={styles.card} aria-label="People and roles">
        <p className={styles.label}>People and roles</p>
        <p className={styles.text}>{`${count(roles, 'role', 'roles')} in use · ${count(people, 'person', 'people')}`}</p>
        <Link className={styles.link} href="/admin/users">
          Open people and roles
        </Link>
      </section>

      <section className={styles.card} aria-label="Sharing with the network">
        <p className={styles.label}>Sharing with the network</p>
        <p className={styles.text}>You share only what you agree to.</p>
      </section>

      <section className={styles.card} aria-label="Settings in force">
        <p className={styles.label}>Settings in force</p>
        <p className={styles.text}>
          {config === null ? 'No settings are in force yet.' : `Version ${config.version}, since ${dayOf(config.effectiveFrom)}`}
        </p>
      </section>
    </aside>
  );
}
