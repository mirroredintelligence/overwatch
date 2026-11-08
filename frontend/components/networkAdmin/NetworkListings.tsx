'use client';

import { useEffect, useId, useRef, useState, type FormEvent, type ReactNode } from 'react';
import { Button } from '@/components/ui/Button';
import { Chip } from '@/components/ui/Chip';
import { StatusTag, type StatusTagVariant } from '@/components/ui/StatusTag';
import { BASE, post, useAdminRead, useNotice, type ListingsRead } from '@/lib/networkAdmin/browser';
import { type ListingReason, type ListingRow, type ListingStatus } from '@/lib/networkAdmin/views';
import { LISTING_STATUS_WORD, REASON_WORDS } from '@/lib/networkAdmin/words';
import styles from './NetworkListings.module.css';
import { OwnedNetworkGate } from './OwnedNetworkGate';

// The listings of the network (TEN-080, board NListings). The owner admits a member's service to the network,
// declines it, pauses it and reinstates it. A decline or a pause asks for its reason in place, beside the table,
// from the fixed codes, never free text. A listing carries the organisation's name and its own reference for the
// service, never a person or a number (the back end's listing has no service name yet: a known issue).

type Decision = 'decline' | 'suspend';
const DONE: Record<'admit' | 'reinstate' | Decision, string> = {
  admit: 'Listing admitted.',
  reinstate: 'Listing reinstated.',
  decline: 'Listing declined.',
  suspend: 'Listing paused.',
};

/** The filter's chips, in the order the board shows them. */
const FILTERS: readonly ListingStatus[] = ['pending', 'admitted', 'suspended', 'declined', 'withdrawn'];

const STATUS_TAG: Readonly<Record<ListingStatus, StatusTagVariant>> = {
  pending: 'waiting',
  admitted: 'live',
  suspended: 'paused',
  declined: 'closed',
  withdrawn: 'closed',
};

const TEXT: Record<Decision, { verb: string; body: string; button: string }> = {
  decline: { verb: 'Decline', body: 'A declined listing is closed. The organisation can ask again for the service.', button: 'Decline the listing' },
  suspend: {
    verb: 'Pause',
    body: 'It leaves the live board now and shows as paused. Say why: the reason is kept in the history.',
    button: 'Pause the listing',
  },
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
  const [filter, setFilter] = useState<ListingStatus>('pending');
  const [deciding, setDeciding] = useState<{ listing: ListingRow; decision: Decision } | null>(null);
  // The button that opened the decision panel, so that focus goes back to it when the panel closes.
  const opener = useRef<HTMLElement | null>(null);

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
  const { listings } = state.data;
  const countOf = (status: ListingStatus) => listings.filter((listing) => listing.status === status).length;
  const shown = listings.filter((listing) => listing.status === filter);

  function closeDecision() {
    setDeciding(null);
    opener.current?.focus();
  }

  return (
    <>
      {notice !== null ? (
        <p role={notice.ok ? 'status' : 'alert'} className={notice.ok ? styles.ok : styles.problem}>
          {notice.text}
        </p>
      ) : null}
      <div className={styles.columns}>
        <div className={styles.column}>
          <div role="group" aria-label="Filter by status" className={styles.chips}>
            {FILTERS.map((status) => (
              <Chip key={status} pressed={filter === status} onPressedChange={() => setFilter(status)} dataEl={`NADM-LISTING-FILTER-${status.toUpperCase()}`}>
                {`${LISTING_STATUS_WORD[status]} ${countOf(status)}`}
              </Chip>
            ))}
          </div>
          <Panel heading={state.data.network.name}>
            <div className={styles.scroll}>
              <table className={styles.table} data-el="NADM-LISTINGS-TABLE">
                <caption className={styles.srOnly}>Listings</caption>
                <thead>
                  <tr>
                    <th scope="col">Organisation</th>
                    <th scope="col">Service</th>
                    <th scope="col">Status</th>
                    <th scope="col">
                      <span className={styles.srOnly}>Action</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {listings.length === 0 ? (
                    <tr>
                      <td colSpan={4}>
                        Nothing here yet.
                        <span className={styles.muted}>{' Organisations list their own services. Each one appears here once it is listed.'}</span>
                      </td>
                    </tr>
                  ) : shown.length === 0 ? (
                    <tr>
                      <td colSpan={4}>No listings with this status.</td>
                    </tr>
                  ) : (
                    shown.map((listing) => {
                      const what = ` ${listing.serviceRef} of ${listing.organisation}`;
                      return (
                        <tr key={listing.id} data-row-ref={listing.id}>
                          <td>{listing.organisation}</td>
                          <td>{listing.serviceRef}</td>
                          <td>
                            <StatusTag variant={STATUS_TAG[listing.status]}>{LISTING_STATUS_WORD[listing.status]}</StatusTag>
                          </td>
                          <td>
                            <div className={styles.actions}>
                              {listing.status === 'pending' ? (
                                <>
                                  <Button variant="primary" busy={busy === listing.id} dataEl="NADM-LISTING-ADMIT-BTN" onClick={() => void act(listing, 'admit')}>
                                    Admit{' '}<span className={styles.srOnly}>{what.trim()}</span>
                                  </Button>
                                  <Button
                                    variant="secondary"
                                    dataEl="NADM-LISTING-DECLINE-BTN"
                                    onClick={(event) => {
                                      opener.current = event.currentTarget;
                                      setDeciding({ listing, decision: 'decline' });
                                    }}
                                  >
                                    Decline{' '}<span className={styles.srOnly}>{what.trim()}</span>
                                  </Button>
                                </>
                              ) : null}
                              {listing.status === 'admitted' ? (
                                <Button
                                  variant="neutral"
                                  dataEl="NADM-LISTING-PAUSE-BTN"
                                  onClick={(event) => {
                                    opener.current = event.currentTarget;
                                    setDeciding({ listing, decision: 'suspend' });
                                  }}
                                >
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
          </Panel>
        </div>

        <div className={styles.column}>
          {deciding !== null ? (
            <DecisionPanel
              key={`${deciding.listing.id}-${deciding.decision}`}
              listing={deciding.listing}
              decision={deciding.decision}
              query={query}
              onClose={closeDecision}
              onDone={() => {
                say(true, DONE[deciding.decision]);
                setDeciding(null);
                reload();
              }}
            />
          ) : null}
          <Panel heading="What viewers see" dashed>
            <p className={styles.text}>
              A paused service is one tile: ◌ Not updated, &quot;?&quot;, &quot;Phone to confirm&quot;, &quot;Not available on the network. Phone to confirm.&quot; No new status word.
            </p>
          </Panel>
          <p className={styles.muted}>Each button appears only for the states it applies to. Every decision is dated in History.</p>
        </div>
      </div>
    </>
  );
}

function Panel({ heading, dashed = false, children }: { heading: string; dashed?: boolean; children: ReactNode }) {
  const id = useId();
  return (
    <section aria-labelledby={id} className={dashed ? `${styles.card} ${styles.dashed}` : styles.card}>
      <h2 id={id} className={styles.heading}>
        {heading}
      </h2>
      {children}
    </section>
  );
}

function DecisionPanel({
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
  const id = useId();
  const heading = useRef<HTMLHeadingElement>(null);
  const [reason, setReason] = useState<ListingReason | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const words = TEXT[decision];

  // The panel opens with its name, so a screen reader says what the person is now deciding.
  useEffect(() => {
    heading.current?.focus();
  }, []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    if (reason === null) {
      setError('Choose a reason.');
      return;
    }
    setError(null);
    setProblem(null);
    setBusy(true);
    const result = await post(`${BASE}/listings/${encodeURIComponent(listing.id)}/${decision}`, query, { reason });
    setBusy(false);
    if (result.ok) onDone();
    else setProblem('That could not be done. Try again.');
  }

  return (
    <section aria-labelledby={id} className={`${styles.card} ${styles.decision}`}>
      <h2 id={id} ref={heading} tabIndex={-1} className={styles.heading}>
        {`${words.verb} ${listing.serviceRef}`}
      </h2>
      <p className={styles.muted}>{`${listing.serviceRef} of ${listing.organisation}`}</p>
      <p className={styles.text}>{words.body}</p>
      <form className={styles.stack} onSubmit={submit} noValidate>
        <fieldset className={styles.fieldset} data-el="NADM-LISTING-REASON-GROUP">
          <legend className={styles.legend}>Reason</legend>
          <div className={styles.reasons}>
            {REASON_WORDS.map(([code, word]) => (
              <label key={code} className={styles.reason}>
                <input
                  type="radio"
                  className={styles.reasonInput}
                  name={`${id}-reason`}
                  value={code}
                  checked={reason === code}
                  onChange={() => {
                    setReason(code);
                    setError(null);
                  }}
                />
                <span className={styles.reasonChip}>{word}</span>
              </label>
            ))}
          </div>
          {error !== null ? <p className={styles.problem}>{error}</p> : null}
        </fieldset>
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
    </section>
  );
}
