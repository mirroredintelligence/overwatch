'use client';

import { Button } from '@/components/ui/Button';
import { useOperatorRead } from '@/lib/operator/browser';
import type { parseSupportTickets, parseTenantList } from '@/lib/operator/views';
import { supportStateWord } from '@/lib/operator/words';
import { reasonWord, whenText } from '@/lib/tenantAdmin/words';
import styles from '@/components/admin/admin.module.css';

// A support person's own requests (TEN-083, DEC-1003): the tenant by its name (its id when the list has no
// name for it), where each request stands in words, and the way to ask for another. The back end lists only
// the caller's own.

type Tickets = ReturnType<typeof parseSupportTickets>;
type Tenants = ReturnType<typeof parseTenantList>;

export function SupportRequestList() {
  const tickets = useOperatorRead<Tickets>('/api/bff/platform/support-tickets');
  const tenants = useOperatorRead<Tenants>('/api/bff/platform/tenants');
  const nameOf = (id: string) => (tenants.state.status === 'ok' ? (tenants.state.data.tenants.find((t) => t.id === id)?.displayName ?? id) : id);
  return (
    <main className={styles.page}>
      <h1 className={styles.title}>Support requests</h1>
      <p className={styles.lede}>You can ask to look into one active tenant at a time. Nothing opens until the tenant’s administrator approves and gives you a code.</p>
      <div className={styles.actions}>
        <Button variant="primary" href="/operator/support/new" dataEl="OP-SUPPORT-NEW-BTN">
          Ask for access
        </Button>
      </div>
      {tickets.state.status === 'loading' ? <p className={styles.muted}>Loading your requests.</p> : null}
      {tickets.state.status === 'failed' ? (
        <p role="alert" className={styles.problem}>
          We could not load your requests.
        </p>
      ) : null}
      {tickets.state.status === 'ok' && tickets.state.data.tickets.length === 0 ? <p className={styles.text}>You have not asked for access to any tenant.</p> : null}
      {tickets.state.status === 'ok' && tickets.state.data.tickets.length > 0 ? (
        <ul className={styles.list}>
          {tickets.state.data.tickets.map((ticket) => (
            <li key={ticket.id}>
              <article className={styles.fieldset} aria-label={`Request ${ticket.id}`}>
                <div className={styles.row}>
                  <span className={ticket.state === 'opened' ? styles.tag : `${styles.tag} ${styles.tagDashed}`}>{supportStateWord(ticket.state)}</span>
                  <span className={styles.text}>{nameOf(ticket.tenantId)}</span>
                </div>
                <p className={styles.text}>{ticket.reason}</p>
                <p className={styles.muted}>{`${reasonWord(ticket.reasonCode)}. Asked ${whenText(ticket.requestedAt)}.`}</p>
                <p className={styles.text}>
                  <a className={styles.link} href={`/operator/support/tickets/${ticket.id}`} aria-label={`Open request ${ticket.id}`}>
                    Open request
                  </a>
                </p>
              </article>
            </li>
          ))}
        </ul>
      ) : null}
    </main>
  );
}
