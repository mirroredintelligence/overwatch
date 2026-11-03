'use client';

import { useCallback, useEffect, useState } from 'react';
import { NetworkUnavailable } from '@/components/scope/NetworkUnavailable';
import { ReadOnlyNote } from '@/components/scope/ReadOnlyNote';
import { ScopeHeader } from '@/components/scope/ScopeHeader';
import { ScopeNotice } from '@/components/scope/ScopeNotice';
import { ShapeIcon, STATUS_LABELS, STATUS_SHAPES, type StatusCode } from '@/components/ui/StatusBadge';
import { londonTime } from '@/lib/board/format';
import { POLL_INTERVAL_MS } from '@/lib/board/liveness';
import { readNetworkView } from '@/lib/network/browser';
import { organisationsOf } from '@/lib/network/orgs';
import { NETWORK_ROUTES } from '@/lib/network/links';
import { parseBoard, parseSystemNow } from '@/lib/network/parse';
import type { NetworkBoard, NetworkSystemNow, SystemNowKey } from '@/lib/network/types';
import { NetworkScope } from './NetworkScope';
import styles from './NetworkHomeView.module.css';

// The counts of the advisor's home and of the executive's home over the network's rows (docs/design/
// network-ui.md section 9, WB11; the known issue W10-K3; the board NHome and PH4): the five counts by status as
// tiles, the organisations that share with the number of services each shares, two actions, and the scope
// header. A network row has no pending count and no next-due time, so there are none; no service is named. The
// advisor's calls, cases and bookings and the executive's alerts are the organisation's own: this page offers
// none, and says so for the executive (DEC-136 item 9). A read that fails keeps the last good figures and says so;
// it is never zeros. The organisations come from the board read; if that read fails, the card says so and the
// counts stay.

type Audience = 'advisor' | 'exec';

const COUNTED: readonly { key: SystemNowKey; status: StatusCode; id: string }[] = [
  { key: 'accepting', status: 'accepting', id: 'ACCEPTING' },
  { key: 'limited', status: 'limited', id: 'LIMITED' },
  { key: 'not-accepting', status: 'not-accepting', id: 'NOT-ACCEPTING' },
  { key: 'over-capacity', status: 'over-capacity', id: 'OVER-CAPACITY' },
  { key: 'not-updated', status: 'not-updated', id: 'NOT-UPDATED' },
];

const countWord = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;
const REASON = (n: number) => `${n} ${n === 1 ? 'service is' : 'services are'} limited, not accepting or over capacity.`;

type Load = { kind: 'loading' } | { kind: 'ready'; now: NetworkSystemNow; stale: boolean } | { kind: 'refused' } | { kind: 'failed' };
type Share = { kind: 'loading' } | { kind: 'ready'; board: NetworkBoard } | { kind: 'failed' };

// Each organisation once, the viewer's own first and marked, with the number of the network's rows it shares.
function sharesOf(board: NetworkBoard, ownOrganisation: string | null) {
  return organisationsOf(
    board.entries.map((entry) => entry.organisationName),
    ownOrganisation,
  ).map((org) => ({ ...org, count: board.entries.filter((entry) => entry.organisationName === org.name).length }));
}

function Home({ audience, networkId, networkName, ownOrganisation, ownHref }: { audience: Audience; networkId: string; networkName: string; ownOrganisation: string | null; ownHref: string }) {
  const [load, setLoad] = useState<Load>({ kind: 'loading' });
  const [share, setShare] = useState<Share>({ kind: 'loading' });

  const read = useCallback(async () => {
    const [result, board] = await Promise.all([
      readNetworkView('system-now', networkId, (body) => parseSystemNow(body, 'bff')),
      readNetworkView('board', networkId, (body) => parseBoard(body, 'bff')),
    ]);
    if (board.ok) setShare({ kind: 'ready', board: board.data });
    else setShare((previous) => (previous.kind === 'ready' ? previous : { kind: 'failed' }));
    if (result.ok) setLoad({ kind: 'ready', now: result.data, stale: false });
    else if ([401, 403, 404].includes(result.status)) setLoad({ kind: 'refused' });
    else setLoad((previous) => (previous.kind === 'ready' ? { ...previous, stale: true } : { kind: 'failed' }));
  }, [networkId]);

  useEffect(() => {
    const first = setTimeout(() => void read(), 0);
    const timer = setInterval(() => void read(), POLL_INTERVAL_MS);
    return () => {
      clearTimeout(first);
      clearInterval(timer);
    };
  }, [read]);

  if (load.kind === 'refused') {
    return (
      <main className={styles.page}>
        <NetworkUnavailable reason="not-available" ownHref={ownHref} />
      </main>
    );
  }

  const now = load.kind === 'ready' ? load.now : null;
  return (
    <main className={styles.page}>
      <ScopeHeader scope="network" networkName={networkName} switchTo={{ ownHref, networkHref: NETWORK_ROUTES.home }} />
      <ReadOnlyNote />
      <div className={styles.heading}>
        <h1 className={styles.title}>Network home</h1>
        {now !== null ? <p className={styles.summary}>{`${countWord(now.services, 'service', 'services')} from ${countWord(now.organisations, 'organisation', 'organisations')}`}</p> : null}
      </div>
      {load.kind === 'loading' ? <p role="status">Loading the network</p> : null}
      {load.kind === 'failed' || (load.kind === 'ready' && load.stale) ? <p role="alert">The network could not be read. Try again shortly.</p> : null}
      {now !== null ? (
        <>
          {now.alert.raised ? (
            <ScopeNotice tone="warning" title="Network pressure is high">
              {`${REASON(now.alert.limitedOrWorse)} High from ${now.alert.highFrom}.`}
            </ScopeNotice>
          ) : null}
          <section aria-label="Counts by status">
            <ul className={styles.tiles}>
              {COUNTED.map(({ key, status, id }) => (
                <li key={key} className={styles.tile} data-status={status}>
                  <span className={styles.figure} data-el={`NET-HOME-COUNT-${id}`}>
                    {now.byStatus[key]}
                  </span>
                  <span className={styles.label}>
                    <span className={styles.shape}>
                      <ShapeIcon shape={STATUS_SHAPES[status]} />
                    </span>
                    {STATUS_LABELS[status]}
                  </span>
                </li>
              ))}
            </ul>
          </section>
          {now.byStatus.unavailable > 0 ? <p className={styles.muted}>{`${now.byStatus.unavailable} not available on the network`}</p> : null}
          <p className={styles.muted}>{`As at ${londonTime(now.generatedAt)}`}</p>
        </>
      ) : null}
      {audience === 'exec' ? <p className={styles.muted}>Alerts are for your own organisation only.</p> : null}
      <div className={styles.split}>
        {now !== null ? (
          <section aria-label="Who shares" className={styles.card}>
            <h2 className={styles.eyebrow}>Who shares</h2>
            {share.kind === 'failed' ? <p className={styles.muted}>The organisations could not be read.</p> : null}
            {share.kind === 'ready' ? (
              <ul className={styles.chips}>
                {sharesOf(share.board, ownOrganisation).map((org) => (
                  <li key={org.ref} className={org.own ? styles.chipOwn : styles.chip}>
                    {`${org.name} · ${org.count}${org.own ? ' · Your organisation' : ''}`}
                  </li>
                ))}
              </ul>
            ) : null}
            <p className={styles.muted}>Figures are reported by each organisation. Not ranked.</p>
          </section>
        ) : null}
        <div className={`${styles.card} ${styles.actions}`}>
          <a href={NETWORK_ROUTES.board} className={styles.primary}>
            {audience === 'advisor' ? 'Open the network board view' : 'Open the network board'}
          </a>
          <a href={NETWORK_ROUTES.services} className={styles.secondary}>
            See the services
          </a>
        </div>
      </div>
      <p className={styles.footnote}>No patient information on this screen</p>
    </main>
  );
}

export function NetworkHomeView({ audience, ownHref }: { audience: Audience; ownHref: string }) {
  return (
    <NetworkScope ownHref={ownHref} networkHref={NETWORK_ROUTES.home}>
      {({ network, ownOrganisation }) => <Home audience={audience} networkId={network.id} networkName={network.name} ownOrganisation={ownOrganisation} ownHref={ownHref} />}
    </NetworkScope>
  );
}
