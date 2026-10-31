'use client';

import { useEffect, useState } from 'react';
import { OrgLabel } from '@/components/scope/OrgLabel';
import { ScopeHeader } from '@/components/scope/ScopeHeader';
import { ScopeNotice } from '@/components/scope/ScopeNotice';
import { NetworkUnavailable } from '@/components/scope/NetworkUnavailable';
import { readNetworkView } from '@/lib/network/browser';
import { dayText } from '@/lib/network/entries';
import { NETWORK_ROUTES } from '@/lib/network/links';
import { ownRow } from '@/lib/network/orgs';
import { parseDirectory } from '@/lib/network/parse';
import type { NetworkDirectoryEntry } from '@/lib/network/types';
import { NetworkScope } from './NetworkScope';
import styles from './Network.module.css';

// What members that left, or that stopped sharing, had shared (docs/design/network-ui.md, NetworkHistory,
// TEN-070). Read only, with the day. It is history: those services are not on the live board, and the page
// says so. A service that was only changed (its entry replaced by a newer one) is not a departure and is
// not listed.

type Load = { kind: 'loading' } | { kind: 'ready'; entries: NetworkDirectoryEntry[] } | { kind: 'refused' } | { kind: 'failed' };

function Ended({ networkId, networkName, ownOrganisation, ownHref }: { networkId: string; networkName: string; ownOrganisation: string | null; ownHref: string }) {
  const [load, setLoad] = useState<Load>({ kind: 'loading' });

  useEffect(() => {
    let current = true;
    void readNetworkView('directory', networkId, (body) => parseDirectory(body, 'bff'), 'history=true').then((result) => {
      if (!current) return;
      if (result.ok) {
        setLoad({ kind: 'ready', entries: result.data.entries.filter((e) => e.endedAt !== null && (e.endReason === 'left' || e.endReason === 'grant-ended')) });
      } else if ([401, 403, 404].includes(result.status)) setLoad({ kind: 'refused' });
      else setLoad({ kind: 'failed' });
    });
    return () => {
      current = false;
    };
  }, [networkId]);

  if (load.kind === 'refused') return <main className={styles.page}><NetworkUnavailable reason="not-available" ownHref={ownHref} /></main>;
  return (
    <main className={styles.page}>
      <h1 className={styles.title}>{`${networkName} history`}</h1>
      <ScopeHeader scope="network" networkName={networkName} switchTo={{ ownHref, networkHref: NETWORK_ROUTES.board }} />
      <ScopeNotice tone="warning" title="This is history. These services are not on the live board." />
      {load.kind === 'loading' ? <p role="status">Loading the history</p> : null}
      {load.kind === 'failed' ? <p role="alert">The history could not be read. Try again shortly.</p> : null}
      {load.kind === 'ready' && load.entries.length === 0 ? <p className={styles.muted}>No organisation has left or stopped sharing.</p> : null}
      {load.kind === 'ready' && load.entries.length > 0 ? (
        <ul className={styles.list} aria-label="Services that are no longer shared">
          {load.entries.map((entry) => (
            <li key={`${entry.rowRef}-${entry.endedAt}`} className={styles.row} data-el="NET-BOARD-ROW" data-service-ref={entry.rowRef}>
              <h2 className={styles.rowTitle}>{entry.serviceName}</h2>
              <OrgLabel name={entry.organisationName} own={ownRow(entry.organisationName, ownOrganisation)} />
              <p className={styles.muted}>
                {entry.endReason === 'left' ? `Left the network on ${dayText(entry.endedAt as string)}` : `Stopped sharing on ${dayText(entry.endedAt as string)}`}
              </p>
            </li>
          ))}
        </ul>
      ) : null}
    </main>
  );
}

export function NetworkHistoryView({ ownHref }: { ownHref: string }) {
  return (
    <NetworkScope ownHref={ownHref} networkHref={NETWORK_ROUTES.history}>
      {({ network, ownOrganisation }) => <Ended networkId={network.id} networkName={network.name} ownOrganisation={ownOrganisation} ownHref={ownHref} />}
    </NetworkScope>
  );
}
