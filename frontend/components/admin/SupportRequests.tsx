'use client';

import { useState } from 'react';
import { Button } from '@/components/ui/Button';
import { adminSend, useAdminRead, useSubmitKey } from '@/lib/tenantAdmin/browser';
import type { parseTicket, parseTicketApproval } from '@/lib/tenantAdmin/views';
import { reasonWord, stateWord, whenText } from '@/lib/tenantAdmin/words';
import styles from './admin.module.css';

// The administrator's side of the support tickets (TEN-076, TEN-084, DEC-1003): a support person asks to
// look into this organisation with a reason; the administrator approves it, refuses it, or takes an approved
// code or an open access back at once. The one-time code is in the answer to an approval and nowhere else:
// it is held in this component's memory until the administrator says it has been passed on, and is never put
// in storage, a cookie or the address, or shown again.

type Ticket = ReturnType<typeof parseTicket>;
type Approval = ReturnType<typeof parseTicketApproval>;

export function SupportRequests() {
  const { state, reload } = useAdminRead<{ tickets: Ticket[] }>('/api/bff/tenant/support-tickets');
  const [code, setCode] = useState<{ code: string; ticket: string } | null>(null);
  const [problem, setProblem] = useState('');
  const [busyId, setBusyId] = useState<string | null>(null);
  const keys = useSubmitKey();

  async function act(ticket: Ticket, what: 'approve' | 'refuse' | 'take-back') {
    if (busyId !== null) return;
    setBusyId(ticket.id);
    setProblem('');
    const base = `/api/bff/tenant/support-tickets/${ticket.id}`;
    const result =
      what === 'approve'
        ? await adminSend<Approval>('POST', `${base}/approval`, undefined, keys.key())
        : what === 'refuse'
          ? await adminSend<Ticket>('POST', `${base}/refusal`, undefined, keys.key())
          : await adminSend<Ticket>('DELETE', `${base}/access`, undefined, keys.key());
    setBusyId(null);
    keys.fresh();
    if (result.ok) {
      if (what === 'approve') setCode({ code: (result.data as Approval).code, ticket: ticket.id });
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

  return (
    <main className={styles.page}>
      <h1 className={styles.title}>Support requests</h1>
      <p className={styles.lede}>
        A support person can ask to look into your organisation to help with a fault. Nothing opens until you approve it and give them a code. The code works once, for one hour.
      </p>

      {code !== null ? (
        <section className={styles.panel} aria-labelledby="code-heading">
          <h2 id="code-heading" className={styles.title}>
            Give this code to the support person
          </h2>
          <p className={styles.code} data-el="ADMIN-ONE-TIME-CODE">
            {code.code}
          </p>
          <p className={styles.text}>It is not shown again. It works for four hours and opens one access to your organisation for one hour.</p>
          <p className={styles.text}>If you lose it, take the code back and ask the support person to ask again.</p>
          <div className={styles.actions}>
            <Button variant="primary" onClick={() => setCode(null)} dataEl="ADMIN-CODE-DONE-BTN">
              I have given the code
            </Button>
          </div>
        </section>
      ) : null}

      {problem !== '' ? (
        <p role="alert" className={styles.problem}>
          {problem}
        </p>
      ) : null}
      {state.status === 'loading' ? <p className={styles.muted}>Loading the support requests.</p> : null}
      {state.status === 'failed' ? (
        <p role="alert" className={styles.problem}>
          We could not load the support requests.
        </p>
      ) : null}
      {state.status === 'ok' && state.data.tickets.length === 0 ? <p className={styles.text}>Nobody has asked to look into your organisation.</p> : null}
      {state.status === 'ok' && state.data.tickets.length > 0 ? (
        <ul className={styles.list}>
          {state.data.tickets.map((ticket) => (
            <li key={ticket.id}>
              <TicketCard ticket={ticket} busy={busyId === ticket.id} onAct={(what) => void act(ticket, what)} />
            </li>
          ))}
        </ul>
      ) : null}
    </main>
  );
}

function TicketCard({ ticket, busy, onAct }: { ticket: Ticket; busy: boolean; onAct: (what: 'approve' | 'refuse' | 'take-back') => void }) {
  return (
    <article className={styles.fieldset} aria-label={`Request ${ticket.id}`}>
      <div className={styles.row}>
        <span className={ticket.state === 'opened' ? styles.tag : `${styles.tag} ${styles.tagDashed}`}>{stateWord(ticket.state)}</span>
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
