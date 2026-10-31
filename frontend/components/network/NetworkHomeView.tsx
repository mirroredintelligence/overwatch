'use client';

import { useCallback, useEffect, useState } from 'react';
import { NetworkUnavailable } from '@/components/scope/NetworkUnavailable';
import { ReadOnlyNote } from '@/components/scope/ReadOnlyNote';
import { ScopeHeader } from '@/components/scope/ScopeHeader';
import { ScopeNotice } from '@/components/scope/ScopeNotice';
import { StatusBadge, type StatusCode } from '@/components/ui/StatusBadge';
import { londonTime } from '@/lib/board/format';
import { POLL_INTERVAL_MS } from '@/lib/board/liveness';
import { readNetworkView } from '@/lib/network/browser';
import { NETWORK_ROUTES } from '@/lib/network/links';
import { parseSystemNow } from '@/lib/network/parse';
import type { NetworkSystemNow, SystemNowKey } from '@/lib/network/types';
import counts from '@/components/advisor/BoardCounts.module.css';
import { NetworkScope } from './NetworkScope';
import styles from './Network.module.css';

// The counts of the advisor's home and of the executive's home over the network's rows (docs/design/
// network-ui.md section 9, WB11; the known issue W10-K3): the same five counts each home has, from what the
// network shares, with the scope header. A network row has no pending count and no next-due time, so there
// are none; no organisation and no service is named. The advisor's calls, cases and bookings and the
// executive's alerts are the organisation's own: this page offers none, and says so for the executive
// (DEC-136 item 9). A read that fails keeps the last good counts and says so; it is never zeros.

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

function Home({ audience, networkId, networkName, ownHref }: { audience: Audience; networkId: string; networkName: string; ownHref: string }) {
  const [load, setLoad] = useState<Load>({ kind: 'loading' });

  const read = useCallback(async () => {
    const result = await readNetworkView('system-now', networkId, (body) => parseSystemNow(body, 'bff'));
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
      <h1 className={styles.title}>{audience === 'advisor' ? 'Ready for calls' : networkName}</h1>
      <ScopeHeader scope="network" networkName={networkName} switchTo={{ ownHref, networkHref: NETWORK_ROUTES.home }} />
      <ReadOnlyNote />
      {load.kind === 'loading' ? <p role="status">Loading the network</p> : null}
      {load.kind === 'failed' || (load.kind === 'ready' && load.stale) ? <p role="alert">The network could not be read. Try again shortly.</p> : null}
      {now !== null ? (
        <>
          {now.alert.raised ? (
            <ScopeNotice tone="warning" title="Network pressure is high">
              {`${REASON(now.alert.limitedOrWorse)} High from ${now.alert.highFrom}.`}
            </ScopeNotice>
          ) : null}
          <p className={styles.muted}>{`${countWord(now.services, 'service', 'services')} from ${countWord(now.organisations, 'organisation', 'organisations')}`}</p>
          <p className={styles.muted}>{`As at ${londonTime(now.generatedAt)}`}</p>
          <section aria-label="Counts by status">
            <ul className={counts.counts}>
              {COUNTED.map(({ key, status, id }) => (
                <li key={key} className={counts.row}>
                  <StatusBadge status={status} />
                  <span className={counts.count} data-el={`NET-HOME-COUNT-${id}`}>
                    {now.byStatus[key]}
                  </span>
                </li>
              ))}
            </ul>
          </section>
          {now.byStatus.unavailable > 0 ? <p className={styles.muted}>{`${now.byStatus.unavailable} not available on the network`}</p> : null}
        </>
      ) : null}
      {audience === 'exec' ? <p className={styles.muted}>Alerts are for your own organisation only.</p> : null}
      <p>
        <a href={NETWORK_ROUTES.board}>{audience === 'advisor' ? 'Open the network board view' : 'Open the network board'}</a>
      </p>
      {audience === 'exec' ? (
        <p>
          <a href={NETWORK_ROUTES.services}>See all services in the network</a>
        </p>
      ) : null}
    </main>
  );
}

export function NetworkHomeView({ audience, ownHref }: { audience: Audience; ownHref: string }) {
  return (
    <NetworkScope ownHref={ownHref} networkHref={NETWORK_ROUTES.home}>
      {({ network }) => <Home audience={audience} networkId={network.id} networkName={network.name} ownHref={ownHref} />}
    </NetworkScope>
  );
}
