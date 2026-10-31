'use client';

import { useState, type FormEvent } from 'react';
import { Button } from '@/components/ui/Button';
import { Card } from '@/components/ui/Card';
import { Dialog } from '@/components/ui/Dialog';
import { BASE, post, useAdminRead, useNotice, type ListingsRead } from '@/lib/networkAdmin/browser';
import { LISTING_REASONS, type ListingReason, type ListingRow } from '@/lib/networkAdmin/views';
import { LISTING_STATUS_WORD, REASON_WORDS, reasonWord } from '@/lib/networkAdmin/words';
import styles from '../admin/admin.module.css';
import { OwnedNetworkGate } from './OwnedNetworkGate';

// The listings of the network (TEN-080, design N1: NetworkListings). The owner admits a member's service to
// the network, declines it, pauses it and reinstates it. A reason is one of the fixed codes, never free text.
// A listing carries the organisation's name and its own reference for the service, never a person or a
// number (the back end's listing has no service name yet: a known issue).

type Decision = 'decline' | 'suspend';
const DONE: Record<'admit' | 'reinstate' | Decision, string> = {
  admit: 'Listing admitted.',
  reinstate: 'Listing reinstated.',
  decline: 'Listing declined.',
  suspend: 'Listing paused.',
};

export function NetworkListings() {
  return (
    <main className={styles.page}>
      <h1 className={styles.title}>Listings</h1>
      <OwnedNetworkGate>{(query) => <Listings query={query} />}</OwnedNetworkGate>
    </main>
  );
}

function Listings({ query }: { query: string }) {
  const { state, reload } = useAdminRead<ListingsRead>(`${BASE}/listings${query}`);
  const { notice, say } = useNotice();
  const [busy, setBusy] = useState<string | null>(null);
  const [deciding, setDeciding] = useState<{ listing: ListingRow; decision: Decision } | null>(null);

  async function act(listing: ListingRow, action: 'admit' | 'reinstate') {
    if (busy !== null) return;
    setBusy(listing.id);
    const result = await post(`${BASE}/listings/${encodeURIComponent(listing.id)}/${action}`, query);
    setBusy(null);
    if (result.ok) {
      say(true, DONE[action]);
      reload();
    } else say(false, 'That could not be done. Try again.');
  }

  if (state.status === 'loading') return <p className={styles.muted}>Loading the listings.</p>;
  if (state.status === 'failed') {
    return (
      <p role="alert" className={styles.problem}>
        We could not load the listings.
      </p>
    );
  }
  return (
    <>
      {notice !== null ? (
        <p role={notice.ok ? 'status' : 'alert'} className={notice.ok ? styles.ok : styles.problem}>
          {notice.text}
        </p>
      ) : null}
      <Card heading={state.data.network.name}>
        <div className={styles.scroll}>
          <table className={styles.table} data-el="NADM-LISTINGS-TABLE">
            <caption>Listings</caption>
            <thead>
              <tr>
                <th scope="col">Organisation</th>
                <th scope="col">Service</th>
                <th scope="col">Status</th>
                <th scope="col">Reason</th>
                <th scope="col">
                  <span className={styles.srOnly}>Action</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {state.data.listings.length === 0 ? (
                <tr>
                  <td colSpan={5}>Nothing here yet.</td>
                </tr>
              ) : (
                state.data.listings.map((listing) => {
                  const what = ` ${listing.serviceRef} of ${listing.organisation}`;
                  return (
                    <tr key={listing.id} data-row-ref={listing.id}>
                      <td>{listing.organisation}</td>
                      <td>{listing.serviceRef}</td>
                      <td>
                        <span className={listing.status === 'admitted' ? styles.tag : `${styles.tag} ${styles.tagDashed}`}>{LISTING_STATUS_WORD[listing.status]}</span>
                      </td>
                      <td>{reasonWord(listing.reason)}</td>
                      <td>
                        <div className={styles.actions}>
                          {listing.status === 'pending' ? (
                            <>
                              <Button variant="primary" busy={busy === listing.id} dataEl="NADM-LISTING-ADMIT-BTN" onClick={() => void act(listing, 'admit')}>
                                Admit<span className={styles.srOnly}>{what}</span>
                              </Button>
                              <Button variant="neutral" dataEl="NADM-LISTING-DECLINE-BTN" onClick={() => setDeciding({ listing, decision: 'decline' })}>
                                Decline<span className={styles.srOnly}>{what}</span>
                              </Button>
                            </>
                          ) : null}
                          {listing.status === 'admitted' ? (
                            <Button variant="neutral" dataEl="NADM-LISTING-PAUSE-BTN" onClick={() => setDeciding({ listing, decision: 'suspend' })}>
                              Pause<span className={styles.srOnly}>{what}</span>
                            </Button>
                          ) : null}
                          {listing.status === 'suspended' ? (
                            <Button variant="primary" busy={busy === listing.id} dataEl="NADM-LISTING-REINSTATE-BTN" onClick={() => void act(listing, 'reinstate')}>
                              Reinstate<span className={styles.srOnly}>{what}</span>
                            </Button>
                          ) : null}
                        </div>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </Card>
      {deciding !== null ? (
        <ReasonDialog
          listing={deciding.listing}
          decision={deciding.decision}
          query={query}
          onClose={() => setDeciding(null)}
          onDone={() => {
            say(true, DONE[deciding.decision]);
            setDeciding(null);
            reload();
          }}
        />
      ) : null}
    </>
  );
}

const TEXT: Record<Decision, { title: string; body: string; button: string }> = {
  decline: { title: 'Decline this listing?', body: 'A declined listing is closed. The organisation can ask again for the service.', button: 'Decline' },
  suspend: { title: 'Pause this listing?', body: 'A paused listing stops showing on the network. It shows as not available until it is reinstated.', button: 'Pause' },
};

function ReasonDialog({
  listing,
  decision,
  query,
  onClose,
  onDone,
}: {
  listing: ListingRow;
  decision: Decision;
  query: string;
  onClose: () => void;
  onDone: () => void;
}) {
  const [reason, setReason] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const words = TEXT[decision];

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    if (!(LISTING_REASONS as readonly string[]).includes(reason)) {
      setError('Choose a reason.');
      return;
    }
    setError(null);
    setProblem(null);
    setBusy(true);
    const result = await post(`${BASE}/listings/${encodeURIComponent(listing.id)}/${decision}`, query, { reason: reason as ListingReason });
    setBusy(false);
    if (result.ok) onDone();
    else setProblem('That could not be done. Try again.');
  }

  return (
    <Dialog title={words.title} sub={`${listing.serviceRef} of ${listing.organisation}`} onClose={onClose}>
      <p className={styles.text}>{words.body}</p>
      <form className={styles.stack} onSubmit={submit} noValidate aria-label={words.title}>
        <div className={styles.selectLabel}>
          <label htmlFor="listing-reason">Reason</label>
          <select id="listing-reason" className={styles.select} value={reason} data-el="NADM-LISTING-REASON-SELECT" aria-invalid={error !== null} onChange={(event) => setReason(event.target.value)}>
            <option value="">Choose a reason</option>
            {REASON_WORDS.map(([code, word]) => (
              <option key={code} value={code}>
                {word}
              </option>
            ))}
          </select>
          {error !== null ? <p className={styles.problem}>{error}</p> : null}
        </div>
        {problem !== null ? (
          <p role="alert" className={styles.problem}>
            {problem}
          </p>
        ) : null}
        <div className={styles.actions}>
          <Button variant="primary" type="submit" busy={busy} dataEl="NADM-LISTING-CONFIRM-BTN">
            {words.button}
          </Button>
          <Button variant="neutral" onClick={onClose} dataEl="SCREENS-BOARD-CANCEL-BTN">
            Cancel
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
