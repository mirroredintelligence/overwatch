'use client';

import { useState, type FormEvent } from 'react';
import { TextField } from '@/components/forms/TextField';
import { Button } from '@/components/ui/Button';
import { Loading, Skeleton } from '@/components/ui/Skeleton';
import { StatusTag } from '@/components/ui/StatusTag';
import { operatorSend, useOperatorRead } from '@/lib/operator/browser';
import type { parseAccessOpened, parseSupportTicket, parseTenantList } from '@/lib/operator/views';
import { useSubmitKey } from '@/lib/tenantAdmin/browser';
import { reasonWord, whenText } from '@/lib/tenantAdmin/words';
import { supportTag } from './SupportRequestList';
import styles from './Support.module.css';

// One request of a support person (TEN-083, DEC-1003, board O5): three stages (Asked, They approve, You open it),
// where it stands as shape plus word, the cancellation while it waits, the opening with the one-time code the
// administrator gave (one organisation, one hour, once) and ending the access. The code is typed here and sent
// in one call: it is never kept, shown again or put in an address, and the field is emptied whatever the answer.
// Every refusal of the code is the back end's one 404, said once.

type Ticket = ReturnType<typeof parseSupportTicket>;
type Opened = ReturnType<typeof parseAccessOpened>;
type Tenants = ReturnType<typeof parseTenantList>;

const CODE = /^[A-Z0-9]{4}-[A-Z0-9]{4}$/;

type StageState = 'done' | 'current' | 'todo' | 'stopped';
type Stage = { name: string; state: StageState; sub: string };

const GLYPH: Record<StageState, string> = { done: '●', current: '◐', todo: '○', stopped: '▲' };

/** The three stages of a request, from where it stands. A request that stopped says which stage it stopped at. */
function stagesOf(ticket: Ticket): readonly [Stage, Stage, Stage] {
  const asked: Stage = { name: '1 Asked', state: 'done', sub: whenText(ticket.requestedAt) };
  switch (ticket.state) {
    case 'pending':
      return [asked, { name: '2 They approve', state: 'current', sub: 'Waiting' }, { name: '3 You open it', state: 'todo', sub: 'With their code' }];
    case 'approved':
      return [asked, { name: '2 They approve', state: 'done', sub: whenText(ticket.decidedAt) }, { name: '3 You open it', state: 'current', sub: 'Enter their code' }];
    case 'opened':
      return [asked, { name: '2 They approve', state: 'done', sub: whenText(ticket.decidedAt) }, { name: '3 You open it', state: 'done', sub: whenText(ticket.openedAt) }];
    case 'ended':
      return [asked, { name: '2 They approve', state: 'done', sub: whenText(ticket.decidedAt) }, { name: '3 You open it', state: 'done', sub: whenText(ticket.endedAt) }];
    case 'revoked':
      return [asked, { name: '2 They approve', state: 'done', sub: whenText(ticket.decidedAt) }, { name: '3 You open it', state: 'stopped', sub: 'Taken back' }];
    case 'refused':
      return [asked, { name: '2 They approve', state: 'stopped', sub: 'Not approved' }, { name: '3 You open it', state: 'todo', sub: 'Not opened' }];
    case 'cancelled':
      return [asked, { name: '2 They approve', state: 'stopped', sub: 'Not needed' }, { name: '3 You open it', state: 'todo', sub: 'Not opened' }];
    default:
      return [asked, { name: '2 They approve', state: 'stopped', sub: 'Not in time' }, { name: '3 You open it', state: 'todo', sub: 'Not opened' }];
  }
}

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
      <section className={styles.detail} aria-label="Request">
        <Loading label="Loading the request.">
          <Skeleton shape="title" width="50%" />
          <Skeleton shape="block" />
        </Loading>
      </section>
    );
  }
  if (read.state.status === 'failed') {
    return (
      <section className={styles.detail} aria-label="Request">
        <div role="alert" className={styles.actions}>
          <p className={styles.problemText}>{read.state.http === 404 ? 'We could not find that request.' : 'We could not load the request.'}</p>
          {read.state.http === 404 ? null : (
            <Button variant="secondary" onClick={read.reload}>
              Try again
            </Button>
          )}
        </div>
      </section>
    );
  }
  const ticket = read.state.data;
  const tenantName = tenants.state.status === 'ok' ? (tenants.state.data.tenants.find((t) => t.id === ticket.tenantId)?.displayName ?? ticket.tenantId) : ticket.tenantId;
  const tag = supportTag(ticket.state);
  const stages = stagesOf(ticket);

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
      setSay({ ok: true, text: `Access is open until ${whenText(result.data.access.expiresAt)}. It is for this organisation only.` });
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
    <section className={styles.detail} aria-label={`Request ${ticket.id}`}>
      <div className={styles.detailHead}>
        <h2 className={styles.detailTitle}>{`Request ${ticket.id}`}</h2>
        <StatusTag variant={tag.variant}>{tag.long}</StatusTag>
      </div>

      <ol className={styles.stages} aria-label="Where the request stands">
        {stages.map((stage) => (
          <li key={stage.name} className={styles.stage} data-stage={stage.state} aria-current={stage.state === 'current' ? 'step' : undefined}>
            <span className={styles.stageName}>
              <span aria-hidden="true">{`${GLYPH[stage.state]} `}</span>
              {stage.name}
            </span>
            <span className={styles.stageSub}>{stage.sub}</span>
          </li>
        ))}
      </ol>

      <section aria-label="About the request">
        <dl className={styles.facts}>
          <dt>Organisation</dt>
          <dd>{tenantName}</dd>
          <dt>Why</dt>
          <dd>{ticket.reason}</dd>
          <dt>Type of problem</dt>
          <dd>{reasonWord(ticket.reasonCode)}</dd>
          {ticket.reference !== null ? (
            <>
              <dt>Help-desk ref</dt>
              <dd>{ticket.reference}</dd>
            </>
          ) : null}
          <dt>Lapses</dt>
          <dd>{whenText(ticket.validUntil)}</dd>
        </dl>
      </section>

      {say !== null ? (
        <p role={say.ok ? 'status' : 'alert'} className={styles.say}>
          {say.text}
        </p>
      ) : null}

      {ticket.state === 'pending' ? (
        <>
          <div className={styles.openBox} data-quiet="true">
            <h3 className={styles.openTitle}>Open the access</h3>
            <p className={styles.openText}>Not yet. Their administrator has to approve first.</p>
          </div>
          <div className={styles.actions}>
            <Button variant="neutral" busy={busy} onClick={() => void cancel()} dataEl="OP-TICKET-CANCEL-BTN">
              Cancel this request
            </Button>
          </div>
        </>
      ) : null}

      {ticket.state === 'approved' && !openedNow ? (
        <form className={styles.openBox} onSubmit={open} noValidate aria-label="Open the access">
          <h3 className={styles.openTitle}>Open the access</h3>
          <p className={styles.openText}>The code works once. It opens one access, to this organisation only, for one hour.</p>
          <div className={styles.codeRow}>
            <div className={styles.codeField}>
              <TextField
                id="access-code"
                label="Code from the administrator"
                value={code}
                onChange={(v) => {
                  submitKey.fresh();
                  setCode(v);
                }}
                requirement="none"
                error={codeError}
                autoComplete="off"
                maxLength={9}
              />
            </div>
            <Button variant="primary" type="submit" busy={busy} dataEl="OP-TICKET-OPEN-BTN">
              Open
            </Button>
          </div>
        </form>
      ) : null}

      {ticket.state === 'opened' ? (
        <div className={styles.openBox}>
          <p className={styles.openText}>{`Opened ${whenText(ticket.openedAt)}. It lasts one hour.`}</p>
          <p className={styles.openText}>This console opens and ends the access. It does not read the organisation’s data yet.</p>
          <div className={styles.actions}>
            <Button variant="neutral" busy={busy} onClick={() => void end()} dataEl="OP-TICKET-END-BTN">
              End the access now
            </Button>
          </div>
        </div>
      ) : null}
    </section>
  );
}
