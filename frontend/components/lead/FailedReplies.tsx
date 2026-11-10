'use client';

import { useEffect, useState } from 'react';
import { PageHeader } from '@/components/shell/PageHeader';
import { ConfirmDialog } from '@/components/blocks/ConfirmDialog';
import { Button } from '@/components/ui/Button';
import { Loading, SkeletonRows } from '@/components/ui/Skeleton';
import { CANNOT_DO, leadPost, leadRead } from '@/lib/lead/browser';
import { agoText } from '@/lib/lead/format';
import type { FailedReply } from '@/lib/lead/failedReplies';
import styles from './FailedReplies.module.css';

// Replies we could not take in (DEC-1359). A person replied by text to a prompt and a service the system needs
// was down for every try, so the reply was not recorded and the sender was asked to send it again. Each one is
// listed here with what they wrote, who sent it when we know, and what went wrong, in words. The lead either puts
// it through now ("Process it now": the reply goes the way it would have gone) or says they dealt with it another
// way ("Mark as handled", asked to confirm because it takes the reply off the list for good).

const NOT_LOADED = 'We could not load these replies. Try again shortly.';

/** The BFF's items are already shaped; one that is not is dropped rather than guessed at. */
function isReply(item: unknown): item is FailedReply {
  const reply = item as Partial<FailedReply> | null;
  return typeof reply?.sid === 'string' && typeof reply.receivedAt === 'string' && typeof reply.text === 'string' && typeof reply.problem === 'string';
}

export function FailedReplies() {
  const [items, setItems] = useState<FailedReply[]>([]);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState<string | null>(null);
  const [reads, setReads] = useState(0);
  const [notice, setNotice] = useState('');
  const [busySid, setBusySid] = useState<string | null>(null);
  const [handling, setHandling] = useState<FailedReply | null>(null);
  const [handleError, setHandleError] = useState<string | undefined>(undefined);
  const [now] = useState(() => Date.now());

  useEffect(() => {
    let cancelled = false;
    void leadRead('/api/bff/lead/replies').then((result) => {
      if (cancelled) return;
      setLoading(false);
      if (!result.ok) {
        setItems([]);
        setFailed(result.status === 403 ? CANNOT_DO : NOT_LOADED);
        return;
      }
      const list = (result.body as { items?: unknown } | undefined)?.items;
      if (!Array.isArray(list)) {
        setItems([]);
        setFailed(NOT_LOADED);
        return;
      }
      setFailed(null);
      setItems(list.filter(isReply));
    });
    return () => {
      cancelled = true;
    };
  }, [reads]);

  function tryAgain() {
    setLoading(true);
    setFailed(null);
    setReads((n) => n + 1);
  }

  async function act(reply: FailedReply, action: 'process' | 'handled'): Promise<boolean> {
    const result = await leadPost(`/api/bff/lead/replies/${encodeURIComponent(reply.sid)}`, { action });
    if (!result.ok) {
      const text =
        result.status === 403
          ? CANNOT_DO
          : result.status === 409
            ? 'That reply has already been dealt with. The list will refresh.'
            : action === 'process'
              ? 'We could not process it now. It is still on the list; try again shortly.'
              : 'We could not update the reply. Try again.';
      if (action === 'handled') setHandleError(text);
      else setNotice(text);
      if (result.status === 409) tryAgain();
      return false;
    }
    setItems((current) => current.filter((item) => item.sid !== reply.sid));
    setNotice(action === 'process' ? 'Processed. The reply has gone the way it would have gone.' : 'Marked as handled.');
    return true;
  }

  async function process(reply: FailedReply) {
    setNotice('');
    setBusySid(reply.sid);
    await act(reply, 'process');
    setBusySid(null);
  }

  async function markHandled() {
    if (handling === null) return;
    setBusySid(handling.sid);
    setHandleError(undefined);
    const done = await act(handling, 'handled');
    setBusySid(null);
    if (done) setHandling(null);
  }

  const ready = !loading && failed === null;

  return (
    <main className={styles.page}>
      <PageHeader title="Replies we could not take in" />
      <p className={styles.lede}>
        These people replied by text, but something went wrong on our side and the reply was not recorded. They were asked to send it again. Process one to
        send it through now, or mark it handled if you dealt with it another way.
      </p>

      {failed !== null ? (
        <div role="alert" className={styles.failure}>
          <p className={styles.failureText}>{failed}</p>
          <Button variant="secondary" onClick={tryAgain} dataEl="LEAD-REPLIES-RETRY-BTN">
            Try again
          </Button>
        </div>
      ) : null}

      {loading ? (
        <Loading label="Loading the replies.">
          <SkeletonRows count={3} />
        </Loading>
      ) : null}

      {ready && items.length === 0 ? <p className={styles.empty}>No replies are waiting.</p> : null}

      {ready && items.length > 0 ? (
        <ul className={styles.list} aria-label="Replies waiting">
          {items.map((reply) => (
            <li key={reply.sid} className={styles.row}>
              <div className={styles.top}>
                <span className={styles.who}>{reply.senderName ?? 'Someone we could not identify'}</span>
                <span className={styles.when}>{agoText(reply.receivedAt, now)}</span>
              </div>
              <p className={styles.wrote}>
                <span className={styles.label}>They wrote</span> <q className={styles.text}>{reply.text}</q>
              </p>
              <p className={styles.problem}>{reply.problem}</p>
              <div className={styles.actions}>
                <Button variant="primary" busy={busySid === reply.sid} onClick={() => void process(reply)} dataEl="LEAD-REPLIES-PROCESS-BTN">
                  Process it now
                  <span className={styles.srOnly}>{` for ${reply.senderName ?? 'this sender'}`}</span>
                </Button>
                <Button
                  variant="neutral"
                  onClick={() => {
                    setHandleError(undefined);
                    setHandling(reply);
                  }}
                  dataEl="LEAD-REPLIES-HANDLED-BTN"
                >
                  Mark as handled
                  <span className={styles.srOnly}>{` for ${reply.senderName ?? 'this sender'}`}</span>
                </Button>
              </div>
            </li>
          ))}
        </ul>
      ) : null}

      <p role="status" className={styles.notice}>
        {notice}
      </p>

      {handling === null ? null : (
        <ConfirmDialog
          title="Mark this reply as handled?"
          confirmLabel="Mark as handled"
          cancelLabel="Keep it on the list"
          busy={busySid === handling.sid}
          error={handleError}
          onConfirm={() => void markHandled()}
          onCancel={() => setHandling(null)}
          dataEl="LEAD-REPLIES-HANDLED-CONFIRM"
        >
          <p>It comes off this list and is not sent through. Use this when you dealt with the reply another way, for example by phoning the service.</p>
        </ConfirmDialog>
      )}
    </main>
  );
}
