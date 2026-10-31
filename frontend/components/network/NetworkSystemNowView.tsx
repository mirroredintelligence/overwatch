'use client';

import { useCallback, useEffect, useState } from 'react';
import { NetworkUnavailable } from '@/components/scope/NetworkUnavailable';
import { ScopeHeader } from '@/components/scope/ScopeHeader';
import { ScopeNotice } from '@/components/scope/ScopeNotice';
import { londonTime } from '@/lib/board/format';
import { POLL_INTERVAL_MS } from '@/lib/board/liveness';
import { readNetworkView } from '@/lib/network/browser';
import { NETWORK_ROUTES } from '@/lib/network/links';
import { parseSystemNow } from '@/lib/network/parse';
import type { NetworkSystemNow, SystemNowKey } from '@/lib/network/types';
import { NetworkScope } from './NetworkScope';
import styles from './Network.module.css';

// "System now" of the network (W17, network variant, `GET /network/{id}/system-now`): the counts of the
// network board by status, how many services from how many organisations, and the pressure state. A network
// has no chase cards, ladder or requests: those are an organisation's own, so this is the counts and the
// pressure, naming no organisation and no service. The pressure is a state of the board, said as one, never
// an instruction (H-654, DEC-982). A read that fails keeps the last good counts and says so.

const ROWS: [SystemNowKey, string][] = [
  ['accepting', 'Accepting'],
  ['limited', 'Limited'],
  ['not-accepting', 'Not accepting'],
  ['over-capacity', 'Over capacity'],
  ['not-updated', 'Not updated'],
  ['out-of-hours', 'Out of hours'],
  ['unavailable', 'Not available on the network'],
];

const countWord = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;
const REASON = (n: number) => `${n} ${n === 1 ? 'service is' : 'services are'} limited, not accepting or over capacity.`;

type Load = { kind: 'loading' } | { kind: 'ready'; now: NetworkSystemNow; stale: boolean } | { kind: 'refused' } | { kind: 'failed' };

function Counts({ networkId, networkName, ownHref }: { networkId: string; networkName: string; ownHref: string }) {
  const [load, setLoad] = useState<Load>({ kind: 'loading' });

  const read = useCallback(async () => {
    const result = await readNetworkView('system-now', networkId, (body) => parseSystemNow(body, 'bff'));
    if (result.ok) setLoad({ kind: 'ready', now: result.data, stale: false });
    else if ([401, 403, 404].includes(result.status)) setLoad({ kind: 'refused' });
    // A failed read is never an empty list or zeros: the last good counts stay, marked, or there is a message.
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

  if (load.kind === 'refused') return <main className={styles.page}><NetworkUnavailable reason="not-available" ownHref={ownHref} /></main>;

  const now = load.kind === 'ready' ? load.now : null;
  return (
    <main className={styles.page}>
      <h1 className={styles.title}>{`${networkName} system now`}</h1>
      <ScopeHeader scope="network" networkName={networkName} switchTo={{ ownHref, networkHref: NETWORK_ROUTES['system-now'] }} />
      {load.kind === 'loading' ? <p role="status">Loading the network</p> : null}
      {load.kind === 'failed' || (load.kind === 'ready' && load.stale) ? <p role="alert">The network could not be read. Try again shortly.</p> : null}
      {now !== null ? (
        <>
          {now.alert.raised ? (
            <ScopeNotice tone="warning" title="Network pressure is high">
              {`${REASON(now.alert.limitedOrWorse)} High from ${now.alert.highFrom}.`}
            </ScopeNotice>
          ) : now.alert.level === 'watch' ? (
            <ScopeNotice tone="info" title="Network pressure is rising">
              {`${REASON(now.alert.limitedOrWorse)} Rising from ${now.alert.watchFrom}.`}
            </ScopeNotice>
          ) : null}
          <p className={styles.muted}>{`${countWord(now.services, 'service', 'services')} from ${countWord(now.organisations, 'organisation', 'organisations')}`}</p>
          <p className={styles.muted}>{`As at ${londonTime(now.generatedAt)}`}</p>
          <div role="group" aria-label="Services by status">
            <dl className={styles.counts}>
              {ROWS.map(([key, word]) => (
                <div key={key} className={styles.count}>
                  <dt>{word}</dt>
                  <dd>{now.byStatus[key]}</dd>
                </div>
              ))}
            </dl>
          </div>
        </>
      ) : null}
    </main>
  );
}

export function NetworkSystemNowView({ ownHref }: { ownHref: string }) {
  return (
    <NetworkScope ownHref={ownHref} networkHref={NETWORK_ROUTES['system-now']}>
      {({ network }) => <Counts networkId={network.id} networkName={network.name} ownHref={ownHref} />}
    </NetworkScope>
  );
}
