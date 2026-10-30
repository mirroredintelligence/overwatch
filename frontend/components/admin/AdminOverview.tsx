'use client';

import { Card } from '@/components/ui/Card';
import { useAdminRead } from '@/lib/tenantAdmin/browser';
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

function Loaded({ overview }: { overview: Overview }) {
  const { tenant, config } = overview;
  return (
    <>
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

      <Card heading="Settings in force">
        {config === null ? (
          <p className={styles.text}>No settings are in force yet.</p>
        ) : (
          <p className={styles.text}>{`Version ${config.version}, in force since ${whenText(config.effectiveFrom)}.`}</p>
        )}
        <p className={styles.text}>
          <a className={styles.link} href="/admin/config">
            Settings and versions
          </a>
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
