'use client';

import Link from 'next/link';
import { Card } from '@/components/ui/Card';
import { useAdminRead } from '@/lib/tenantAdmin/browser';
import { MAPPABLE_ROLE_WORDS } from '@/lib/tenantAdmin/roles';
import { whenText } from '@/lib/tenantAdmin/words';
import type { parseOverview } from '@/lib/tenantAdmin/views';
import styles from './admin.module.css';

// The administrator's first page (TEN-076): who the organisation is, which settings are in force and the way
// to each page of the administration. Nothing here is a tenant id, a secret or a person's reference: the BFF
// has dropped them (lib/tenantAdmin/views.ts).

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

export function AdminOverview() {
  const { state } = useAdminRead<Overview>('/api/bff/tenant/overview');
  return (
    <main className={styles.page}>
      <h1 className={styles.title}>Administration</h1>
      {state.status === 'loading' ? <p className={styles.muted}>Loading your organisation.</p> : null}
      {state.status === 'failed' ? (
        <p role="alert" className={styles.problem}>
          We could not load your organisation.
        </p>
      ) : null}
      {state.status === 'ok' ? <Loaded overview={state.data} /> : null}
    </main>
  );
}

type Step = { done: boolean; waiting?: boolean; text: string; href?: string; link?: string };

/** What the organisation still has to do before people can sign in and the service can run: said as a list,
 * each step with its state in words and the page that does it. Nothing is listed when everything is done. */
export function setupSteps(overview: Overview): Step[] {
  const bound = overview.bindings.filter((b) => b.status !== 'revoked');
  const verified = bound.some((b) => b.status === 'verified');
  const waiting = bound.some((b) => b.status === 'pending');
  const groups = overview.mappings.filter((m) => m.status === 'active').length;
  const phone = overview.contacts.some((c) => c.kind === 'coordination-phone');
  return [
    verified
      ? { done: true, text: 'A directory is bound and verified.' }
      : waiting
        ? { done: false, waiting: true, text: 'Your directory is waiting for the platform operator to verify it.' }
        : { done: false, text: 'Bind the directory your people sign in with.', href: '/admin/users', link: 'Users and roles' },
    groups > 0
      ? { done: true, text: 'A group is mapped to a role.' }
      : { done: false, text: 'Map a group to a role, so people can sign in.', href: '/admin/users', link: 'Users and roles' },
    phone
      ? { done: true, text: 'The coordination phone is recorded.' }
      : { done: false, text: 'Add the coordination phone.', href: '/admin/contacts', link: 'Contacts' },
  ];
}

function SetupCard({ overview }: { overview: Overview }) {
  const steps = setupSteps(overview);
  if (steps.every((s) => s.done)) return null;
  return (
    <Card heading="Finish setting up" dataEl="ADMIN-SETUP">
      <ul className={styles.list}>
        {steps.map((step) => (
          <li key={step.text} className={styles.row}>
            <span className={step.done ? styles.tag : `${styles.tag} ${styles.tagDashed}`}>{step.done ? 'Done' : step.waiting === true ? 'Waiting' : 'To do'}</span>
            <span className={styles.text}>
              {step.text}
              {step.href !== undefined ? (
                <>
                  {' '}
                  <a className={styles.link} href={step.href}>
                    {step.link}
                  </a>
                </>
              ) : null}
            </span>
          </li>
        ))}
      </ul>
    </Card>
  );
}

function roleName(code: string): string {
  return MAPPABLE_ROLE_WORDS.find(([value]) => value === code)?.[1] ?? code;
}

function PeopleCard({ overview }: { overview: Overview }) {
  const active = overview.mappings.filter((m) => m.status === 'active');
  return (
    <Card heading="People and groups">
      <p className={styles.text}>People are not listed by name. They sign in with your directory and get the role of the group they belong to.</p>
      {active.length === 0 ? (
        <p className={styles.text}>No group is mapped yet. Until one is, nobody can sign in except you.</p>
      ) : (
        <>
          <p className={styles.text}>{active.length === 1 ? '1 group is in use:' : `${active.length} groups are in use:`}</p>
          <ul className={styles.list}>
            {active.map((m) => (
              <li key={m.groupObjectId} className={styles.text}>
                {roleName(m.role)}
              </li>
            ))}
          </ul>
        </>
      )}
    </Card>
  );
}

function Loaded({ overview }: { overview: Overview }) {
  const { tenant, config } = overview;
  return (
    <>
      <SetupCard overview={overview} />
      <Card heading="Your organisation">
        <dl className={styles.facts}>
          <dt>Name</dt>
          <dd>{tenant.displayName}</dd>
          <dt>Legal name</dt>
          <dd>{tenant.legalName}</dd>
          <dt>ODS code</dt>
          <dd>{tenant.odsCode ?? '-'}</dd>
          <dt>Time zone</dt>
          <dd>{tenant.timeZone}</dd>
          <dt>Status</dt>
          <dd>{tenant.status}</dd>
          <dt>Address</dt>
          <dd>{tenant.host ?? '-'}</dd>
        </dl>
      </Card>

      <PeopleCard overview={overview} />

      <Card heading="Sharing with the network">
        <p className={styles.text}>You share with the network only what you have agreed to, and you can end it at any time.</p>
        <p className={styles.text}>
          <Link className={styles.link} href="/admin/sharing">
            See what you share
          </Link>
        </p>
      </Card>

      <Card heading="Settings in force">
        {config === null ? (
          <p className={styles.text}>No settings are in force yet.</p>
        ) : (
          <p className={styles.text}>{`Version ${config.version}, in force since ${whenText(config.effectiveFrom)}.`}</p>
        )}
        <p className={styles.text}>
          <Link className={styles.link} href="/admin/config">
            Settings and versions
          </Link>
        </p>
      </Card>

      <nav aria-label="Administration pages">
        <ul className={styles.list}>
          {ADMIN_PAGES.map(([name, href]) => (
            <li key={href}>
              <a className={styles.link} href={href}>
                {name}
              </a>
            </li>
          ))}
        </ul>
      </nav>
    </>
  );
}
