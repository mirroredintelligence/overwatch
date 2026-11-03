'use client';

import type { ReactNode } from 'react';
import { Button } from '@/components/ui/Button';
import { Loading, SkeletonRows } from '@/components/ui/Skeleton';
import { StatusTag, type StatusTagVariant } from '@/components/ui/StatusTag';
import { useOperatorRead } from '@/lib/operator/browser';
import type { parseSupportTickets, parseTenantList } from '@/lib/operator/views';
import styles from './Support.module.css';

// A support person's own requests (TEN-083, DEC-1003, board O5): the requests on the left, each by its number and
// the organisation's name (its id when the list has no name for it), where it stands as shape plus word, and the
// way to ask for another. The open request, or the sheet that asks, is passed in: the page that shows it is the
// route (/operator/support, /new or /tickets/<id>). The back end lists only the caller's own.

type Tickets = ReturnType<typeof parseSupportTickets>;
type Tenants = ReturnType<typeof parseTenantList>;

/** Where a request stands: the short word the list shows, the longer one the open request shows, and the shape. */
export const SUPPORT_TAG: Record<string, { variant: StatusTagVariant; short: string; long: string }> = {
  pending: { variant: 'waiting', short: 'Waiting', long: 'Waiting for their administrator' },
  approved: { variant: 'done', short: 'Approved', long: 'Approved: enter the code' },
  opened: { variant: 'live', short: 'Open now', long: 'Open now' },
  ended: { variant: 'done', short: 'Ended', long: 'Ended' },
  refused: { variant: 'todo', short: 'Refused', long: 'Refused' },
  cancelled: { variant: 'todo', short: 'Cancelled', long: 'Cancelled' },
  revoked: { variant: 'closed', short: 'Taken back', long: 'Taken back by the administrator' },
  expired: { variant: 'paused', short: 'Lapsed', long: 'Lapsed' },
};

export function supportTag(state: string) {
  return SUPPORT_TAG[state] ?? { variant: 'todo' as const, short: state, long: state };
}

const SHORT_DATE = new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short' });

function shortDate(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? '' : SHORT_DATE.format(date);
}

export function SupportRequestList({ selectedId, children, sheet }: { selectedId?: string; children?: ReactNode; sheet?: ReactNode }) {
  const tickets = useOperatorRead<Tickets>('/api/bff/platform/support-tickets');
  const tenants = useOperatorRead<Tenants>('/api/bff/platform/tenants');
  const nameOf = (id: string) => (tenants.state.status === 'ok' ? (tenants.state.data.tenants.find((t) => t.id === id)?.displayName ?? id) : id);
  return (
    <>
      <main className={styles.page} inert={sheet !== undefined ? true : undefined}>
        <h1 className={styles.visuallyHidden}>Support requests</h1>
        <section className={styles.listCol} aria-label="Requests">
          <p className={styles.lede}>You can ask to look into one organisation at a time.</p>
          <Button variant="primary" href="/operator/support/new" dataEl="OP-SUPPORT-NEW-BTN">
            Ask for access
          </Button>
          {tickets.state.status === 'loading' ? (
            <Loading label="Loading your requests.">
              <SkeletonRows count={3} />
            </Loading>
          ) : null}
          {tickets.state.status === 'failed' ? (
            <div role="alert" className={styles.problem}>
              <p className={styles.problemText}>We could not load your requests.</p>
              <Button variant="secondary" onClick={tickets.reload}>
                Try again
              </Button>
            </div>
          ) : null}
          {tickets.state.status === 'ok' && tickets.state.data.tickets.length === 0 ? <p className={styles.status}>You have not asked for access to any organisation.</p> : null}
          {tickets.state.status === 'ok' && tickets.state.data.tickets.length > 0 ? (
            <ul className={styles.list}>
              {tickets.state.data.tickets.map((ticket) => {
                const tag = supportTag(ticket.state);
                const current = ticket.id === selectedId;
                return (
                  <li key={ticket.id}>
                    <article className={styles.card} aria-label={`Request ${ticket.id}`} data-current={current ? 'true' : undefined}>
                      <div className={styles.cardText}>
                        <p className={styles.cardTitle}>
                          <a className={styles.cardLink} href={`/operator/support/tickets/${ticket.id}`} aria-label={`Open request ${ticket.id}`} aria-current={current ? 'page' : undefined}>
                            <span>{ticket.id}</span>
                            <span aria-hidden="true"> · </span>
                            <span>{nameOf(ticket.tenantId)}</span>
                          </a>
                        </p>
                        <p className={styles.cardSub}>{`${ticket.reason} · ${shortDate(ticket.requestedAt)}`}</p>
                      </div>
                      <StatusTag variant={tag.variant}>{tag.short}</StatusTag>
                    </article>
                  </li>
                );
              })}
            </ul>
          ) : null}
          <p className={styles.note}>Nothing opens until the organisation’s administrator approves and gives you a code.</p>
        </section>
        <div className={styles.pane}>{children ?? <p className={styles.empty}>Choose a request to see where it stands.</p>}</div>
      </main>
      {sheet}
    </>
  );
}
