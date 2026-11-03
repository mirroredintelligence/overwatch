'use client';

import { useState } from 'react';
import { Button } from '@/components/ui/Button';
import { StatusTag, type StatusTagVariant } from '@/components/ui/StatusTag';
import { Disclose } from '@/components/admin/Disclose';
import { adminSend, useAdminRead, useSubmitKey } from '@/lib/tenantAdmin/browser';
import type { parseTicket, parseTicketApproval } from '@/lib/tenantAdmin/views';
import { reasonWord, stateWord, whenText } from '@/lib/tenantAdmin/words';
import { Loading, SkeletonRows } from '@/components/ui/Skeleton';
import styles from './admin.module.css';

// The administrator's side of the support tickets (TEN-076, TEN-084, DEC-1003): a support person asks to
// look into this organisation with a reason; the administrator approves it, refuses it, or takes an approved
// code or an open access back at once. The one-time code is in the answer to an approval and nowhere else:
// it is held in this component's memory until the administrator says it has been passed on, and is never put
// in storage, a cookie or the address, or shown again. The code is the one live region on the card, so it is
// announced once when it appears.

type Ticket = ReturnType<typeof parseTicket>;
type Approval = ReturnType<typeof parseTicketApproval>;
type Action = 'approve' | 'refuse' | 'take-back';

// Requests still open to the administrator (waiting, approved, or in use) are shown; the rest sit under "Earlier".
const OPEN_STATES = new Set(['pending', 'approved', 'opened']);

const TAG: Record<string, StatusTagVariant> = {
  pending: 'waiting',
  approved: 'todo',
  opened: 'live',
  expired: 'paused',
};

export function SupportRequests() {
  const { state, reload } = useAdminRead<{ tickets: Ticket[] }>('/api/bff/tenant/support-tickets');
  const [code, setCode] = useState<{ code: string; ticket: string } | null>(null);
  const [copied, setCopied] = useState(false);
  const [problem, setProblem] = useState('');
  const [busyId, setBusyId] = useState<string | null>(null);
  const [earlierOpen, setEarlierOpen] = useState(false);
  const keys = useSubmitKey();

  async function act(id: string, what: Action) {
    if (busyId !== null) return;
    setBusyId(id);
    setProblem('');
    const base = `/api/bff/tenant/support-tickets/${id}`;
    const result =
      what === 'approve'
        ? await adminSend<Approval>('POST', `${base}/approval`, undefined, keys.key())
        : what === 'refuse'
          ? await adminSend<Ticket>('POST', `${base}/refusal`, undefined, keys.key())
          : await adminSend<Ticket>('DELETE', `${base}/access`, undefined, keys.key());
    setBusyId(null);
    keys.fresh();
    if (result.ok) {
      if (what === 'approve') {
        setCopied(false);
        setCode({ code: (result.data as Approval).code, ticket: id });
      }
      if (what === 'take-back') setCode((held) => (held?.ticket === id ? null : held));
      reload();
      return;
    }
    if (result.status === 409) {
      setProblem('This request is not waiting for you any more. The list has been read again.');
      reload();
    } else {
      setProblem(
        what === 'approve' ? 'The request could not be approved. Try again.' : what === 'refuse' ? 'The request could not be refused. Try again.' : 'The access could not be taken back. Try again.',
      );
    }
  }

  async function copy(text: string) {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  }

  const tickets = state.status === 'ok' ? state.data.tickets : [];
  const open = tickets.filter((t) => OPEN_STATES.has(t.state));
  const earlier = tickets.filter((t) => !OPEN_STATES.has(t.state));
  const waiting = tickets.filter((t) => t.state === 'pending').length;

  return (
    <main className={styles.page}>
      <div className={styles.headRow}>
        <h1 className={styles.title}>Support requests</h1>
        {waiting > 0 ? <StatusTag variant="waiting">{`${waiting} waiting for you`}</StatusTag> : null}
      </div>
      <p className={styles.lede}>Platform staff can look into your organisation only when you approve and give them a code.</p>

      {code !== null ? (
        <section className={styles.panel} aria-labelledby="code-heading">
          <h2 id="code-heading" className={styles.subheading}>
            Approved. Give them this code.
          </h2>
          <p role="status" className={styles.code} data-el="ADMIN-ONE-TIME-CODE">
            {code.code}
          </p>
          <p className={styles.text}>
            Shown once. It works for 4 hours and opens one access to your organisation for 1 hour. If you lose it, take it back and ask them to ask again.
          </p>
          <div className={styles.actions}>
            <Button variant="neutral" onClick={() => void copy(code.code)} dataEl="ADMIN-CODE-COPY-BTN">
              Copy the code
            </Button>
            {copied ? <span className={styles.muted}>Copied to the clipboard.</span> : null}
          </div>
          <div className={styles.actions}>
            <Button variant="secondary" onClick={() => { setCode(null); setCopied(false); }} dataEl="ADMIN-CODE-DONE-BTN">
              I have passed it on
            </Button>
            <Button variant="neutral" busy={busyId === code.ticket} onClick={() => void act(code.ticket, 'take-back')} dataEl="ADMIN-CODE-TAKE-BACK-BTN">
              Take it back
            </Button>
          </div>
        </section>
      ) : null}

      {problem !== '' ? (
        <p role="alert" className={styles.problem}>
          {problem}
        </p>
      ) : null}
      {state.status === 'loading' ? <Loading label="Loading the support requests."><SkeletonRows count={3} /></Loading> : null}
      {state.status === 'failed' ? (
        <p role="alert" className={styles.problem}>
          We could not load the support requests.
        </p>
      ) : null}
      {state.status === 'ok' && tickets.length === 0 ? <p className={styles.text}>Nobody has asked to look into your organisation.</p> : null}
      {open.length > 0 ? (
        <ul className={styles.list}>
          {open.map((ticket) => (
            <li key={ticket.id}>
              <TicketCard ticket={ticket} busy={busyId === ticket.id} onAct={(what) => void act(ticket.id, what)} />
            </li>
          ))}
        </ul>
      ) : null}
      {earlier.length > 0 ? (
        <Disclose
          open={earlierOpen}
          onToggle={() => setEarlierOpen((value) => !value)}
          title={
            <>
              Earlier requests <span className={styles.muted}>· {earlier.length}</span>
            </>
          }
        >
          <ul className={styles.list}>
            {earlier.map((ticket) => (
              <li key={ticket.id}>
                <TicketCard ticket={ticket} busy={false} onAct={() => undefined} />
              </li>
            ))}
          </ul>
        </Disclose>
      ) : null}
    </main>
  );
}

function TicketCard({ ticket, busy, onAct }: { ticket: Ticket; busy: boolean; onAct: (what: Action) => void }) {
  return (
    <article className={styles.fieldset} aria-label={`Request ${ticket.id}`}>
      <div className={styles.row}>
        <StatusTag variant={TAG[ticket.state] ?? 'closed'}>{stateWord(ticket.state)}</StatusTag>
        <span className={styles.text}>{reasonWord(ticket.reasonCode)}</span>
      </div>
      <p className={styles.text}>{ticket.reason}</p>
      {ticket.reference !== null ? <p className={styles.muted}>{`Help-desk reference ${ticket.reference}`}</p> : null}
      <p className={styles.muted}>{`Asked ${whenText(ticket.requestedAt)}. Lapses ${whenText(ticket.validUntil)}.`}</p>
      <div className={styles.actions}>
        {ticket.state === 'pending' ? (
          <>
            <Button variant="primary" busy={busy} onClick={() => onAct('approve')} dataEl="ADMIN-TICKET-APPROVE-BTN">
              Approve
            </Button>
            <Button variant="secondary" busy={busy} onClick={() => onAct('refuse')} dataEl="ADMIN-TICKET-REFUSE-BTN">
              Refuse
            </Button>
          </>
        ) : null}
        {ticket.state === 'approved' ? (
          <Button variant="neutral" busy={busy} onClick={() => onAct('take-back')} dataEl="ADMIN-TICKET-REVOKE-BTN">
            Take the code back
          </Button>
        ) : null}
        {ticket.state === 'opened' ? (
          <Button variant="neutral" busy={busy} onClick={() => onAct('take-back')} dataEl="ADMIN-TICKET-END-BTN">
            End the access now
          </Button>
        ) : null}
      </div>
    </article>
  );
}
