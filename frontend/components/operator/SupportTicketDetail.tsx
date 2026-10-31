'use client';

import { useState, type FormEvent } from 'react';
import { TextField } from '@/components/forms/TextField';
import { Button } from '@/components/ui/Button';
import { operatorSend, useOperatorRead } from '@/lib/operator/browser';
import type { parseAccessOpened, parseSupportTicket, parseTenantList } from '@/lib/operator/views';
import { supportStateWord } from '@/lib/operator/words';
import { useSubmitKey } from '@/lib/tenantAdmin/browser';
import { reasonWord, whenText } from '@/lib/tenantAdmin/words';
import styles from '@/components/admin/admin.module.css';

// One request of a support person (TEN-083, DEC-1003): where it stands, the cancellation while it waits, the
// opening with the one-time code the administrator gave (one tenant, one hour, once) and ending the access.
// The code is typed here and sent in one call: it is never kept, shown again or put in an address, and the
// field is emptied whatever the answer. Every refusal of the code is the back end's one 404, said once.

type Ticket = ReturnType<typeof parseSupportTicket>;
type Opened = ReturnType<typeof parseAccessOpened>;
type Tenants = ReturnType<typeof parseTenantList>;

const CODE = /^[A-Z0-9]{4}-[A-Z0-9]{4}$/;

export function SupportTicketDetail({ id }: { id: string }) {
  const read = useOperatorRead<Ticket>(`/api/bff/platform/support-tickets/${id}`);
  const tenants = useOperatorRead<Tenants>('/api/bff/platform/tenants');
  const [code, setCode] = useState('');
  const [codeError, setCodeError] = useState<string | null>(null);
  const [say, setSay] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [openedNow, setOpenedNow] = useState(false);
  const submitKey = useSubmitKey();

  if (read.state.status === 'loading') {
    return (
      <main className={styles.page}>
        <p className={styles.muted}>Loading the request.</p>
      </main>
    );
  }
  if (read.state.status === 'failed') {
    return (
      <main className={styles.page}>
        <p role="alert" className={styles.problem}>
          {read.state.http === 404 ? 'We could not find that request.' : 'We could not load the request.'}
        </p>
      </main>
    );
  }
  const ticket = read.state.data;
  const tenantName = tenants.state.status === 'ok' ? (tenants.state.data.tenants.find((t) => t.id === ticket.tenantId)?.displayName ?? ticket.tenantId) : ticket.tenantId;

  async function cancel() {
    if (busy) return;
    setBusy(true);
    setSay(null);
    const result = await operatorSend<Ticket>('POST', `/api/bff/platform/support-tickets/${id}/cancellation`, {}, submitKey.key());
    setBusy(false);
    submitKey.fresh();
    if (result.ok) setSay({ ok: true, text: 'The request is cancelled.' });
    else setSay({ ok: false, text: 'The request could not be taken back. It may have been decided. The page has been read again.' });
    read.reload();
  }

  async function open(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    const typed = code.trim().toUpperCase();
    if (!CODE.test(typed)) {
      setCodeError('Enter the code as it was given, for example K7R4-92QX.');
      return;
    }
    setCodeError(null);
    setBusy(true);
    setSay(null);
    const result = await operatorSend<Opened>('POST', `/api/bff/platform/support-tickets/${id}/access`, { code: typed }, submitKey.key());
    setBusy(false);
    submitKey.fresh();
    setCode('');
    if (result.ok) {
      setOpenedNow(true);
      setSay({ ok: true, text: `Access is open until ${whenText(result.data.access.expiresAt)}. It is for this tenant only.` });
      read.reload();
    } else {
      setSay({ ok: false, text: 'That code did not work. Check it with the administrator, or ask them to take it back and approve again.' });
    }
  }

  async function end() {
    if (busy) return;
    setBusy(true);
    setSay(null);
    const result = await operatorSend<Ticket>('DELETE', `/api/bff/platform/support-tickets/${id}/access`, undefined, submitKey.key());
    setBusy(false);
    submitKey.fresh();
    if (result.ok) setSay({ ok: true, text: 'The access has ended.' });
    else setSay({ ok: false, text: 'The access could not be ended. The page has been read again.' });
    read.reload();
  }

  return (
    <main className={styles.page}>
      <h1 className={styles.title}>{`Request ${ticket.id}`}</h1>
      <div className={styles.row}>
        <span className={ticket.state === 'opened' ? styles.tag : `${styles.tag} ${styles.tagDashed}`}>{supportStateWord(ticket.state)}</span>
        <span className={styles.text}>{tenantName}</span>
      </div>
      <p className={styles.text}>{ticket.reason}</p>
      <p className={styles.muted}>{reasonWord(ticket.reasonCode)}</p>
      {ticket.reference !== null ? <p className={styles.muted}>{`Help-desk reference ${ticket.reference}`}</p> : null}
      <p className={styles.muted}>{`Asked ${whenText(ticket.requestedAt)}. Lapses ${whenText(ticket.validUntil)}.`}</p>

      {say !== null ? (
        <p role={say.ok ? 'status' : 'alert'} className={say.ok ? styles.ok : styles.problem}>
          {say.text}
        </p>
      ) : null}

      {ticket.state === 'pending' ? (
        <div className={styles.actions}>
          <Button variant="neutral" busy={busy} onClick={() => void cancel()} dataEl="OP-TICKET-CANCEL-BTN">
            Cancel the request
          </Button>
        </div>
      ) : null}

      {ticket.state === 'approved' && !openedNow ? (
        <form className={styles.stack} onSubmit={open} noValidate aria-label="Open the access">
          <TextField
            id="access-code"
            label="Code from the administrator"
            value={code}
            onChange={(v) => {
              submitKey.fresh();
              setCode(v);
            }}
            requirement="none"
            hint="The code works once. It opens one access, to this tenant only, for one hour."
            error={codeError}
            autoComplete="off"
            maxLength={9}
          />
          <div className={styles.actions}>
            <Button variant="primary" type="submit" busy={busy} dataEl="OP-TICKET-OPEN-BTN">
              Open access
            </Button>
          </div>
        </form>
      ) : null}

      {ticket.state === 'opened' ? (
        <>
          <p className={styles.text}>{`Opened ${whenText(ticket.openedAt)}. It lasts one hour.`}</p>
          <p className={styles.muted}>This console opens and ends the access. It does not read the tenant’s data yet.</p>
          <div className={styles.actions}>
            <Button variant="neutral" busy={busy} onClick={() => void end()} dataEl="OP-TICKET-END-BTN">
              End the access now
            </Button>
          </div>
        </>
      ) : null}
    </main>
  );
}
