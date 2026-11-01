'use client';

import { useOperatorRead } from '@/lib/operator/browser';
import type { OperatorRole } from '@/lib/operator/session';
import type { parseTenantList } from '@/lib/operator/views';
import { organisationTypeWord, TENANT_STATUS_WORD } from '@/lib/operator/words';
import { Button } from '@/components/ui/Button';
import { whenText } from '@/lib/tenantAdmin/words';
import styles from '@/components/admin/admin.module.css';

// The console's first page (TEN-083): the tenants. The operator sees the type, the address and when a tenant
// was activated and can open or create one; a support person sees the name and the status (the BFF has
// dropped the rest) and can ask to look into an active one.

type List = ReturnType<typeof parseTenantList>;

export function TenantList({ role }: { role: OperatorRole }) {
  const { state } = useOperatorRead<List>('/api/bff/platform/tenants');
  const operator = role === 'platform-operator';
  return (
    <main className={styles.page}>
      <div className={styles.headRow}>
        <div>
          <h1 className={styles.title}>Tenants</h1>
          <p className={styles.muted}>One row per organisation. {operator ? 'Open a tenant to set it up or look after it.' : 'Ask to look into an active one.'}</p>
        </div>
        {operator && state.status === 'ok' && state.data.tenants.length > 0 ? (
          <Button variant="primary" href="/operator/tenants/new" dataEl="OP-CREATE-TENANT-BTN">
            Create a tenant
          </Button>
        ) : null}
      </div>
      {state.status === 'loading' ? <p className={styles.muted}>Loading the tenants.</p> : null}
      {state.status === 'failed' ? (
        <p role="alert" className={styles.problem}>
          We could not load the tenants.
        </p>
      ) : null}
      {state.status === 'ok' && state.data.tenants.length === 0 ? (
        <section className={styles.empty} aria-labelledby="no-tenants">
          <h2 id="no-tenants" className={styles.emptyTitle}>
            There are no tenants yet.
          </h2>
          {operator ? (
            <>
              <p className={styles.text}>
                A tenant is one organisation. Create the first one, then give it an address, bind its directory, map the groups that sign in and add its first administrator to the administrators’ group. It does nothing until you activate it.
              </p>
              <div className={styles.actions}>
                <Button variant="primary" href="/operator/tenants/new" dataEl="OP-CREATE-TENANT-BTN">
                  Create the first tenant
                </Button>
              </div>
            </>
          ) : (
            <p className={styles.text}>When a platform operator creates one and activates it, you can ask to look into it here.</p>
          )}
        </section>
      ) : null}
      {state.status === 'ok' && state.data.tenants.length > 0 ? (
        <div className={styles.scroll}>
          <table className={`${styles.table} ${styles.stackTable}`}>
            <caption>Tenants</caption>
            <thead>
              <tr>
                <th scope="col">Name</th>
                <th scope="col">Status</th>
                {operator ? (
                  <>
                    <th scope="col">Type</th>
                    <th scope="col">Address</th>
                    <th scope="col">Activated</th>
                  </>
                ) : (
                  <th scope="col">Ask to look in</th>
                )}
              </tr>
            </thead>
            <tbody>
              {state.data.tenants.map((t) => (
                <tr key={t.id}>
                  <th scope="row">
                    {operator ? (
                      <a className={styles.link} href={`/operator/tenants/${t.id}`}>
                        {t.displayName}
                      </a>
                    ) : (
                      t.displayName
                    )}
                  </th>
                  <td data-label="Status">
                    <span className={t.status === 'active' ? styles.tag : `${styles.tag} ${styles.tagDashed}`}>{TENANT_STATUS_WORD[t.status] ?? t.status}</span>
                  </td>
                  {operator ? (
                    <>
                      <td data-label="Type">{organisationTypeWord(t.organisationType)}</td>
                      <td data-label="Address">{t.host ?? '-'}</td>
                      <td data-label="Activated">{whenText(t.activatedAt)}</td>
                    </>
                  ) : (
                    <td data-label="Ask to look in">
                      {t.status === 'active' ? (
                        <a className={styles.link} href={`/operator/support/new?for=${t.id}`}>
                          Ask for access<span className={styles.srOnly}>{` to ${t.displayName}`}</span>
                        </a>
                      ) : (
                        '-'
                      )}
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </main>
  );
}
