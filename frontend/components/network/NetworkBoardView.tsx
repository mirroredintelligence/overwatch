'use client';

import { useEffect, useRef, useState } from 'react';
import { NetworkBoard, type StoppedOrganisation } from '@/components/board/NetworkBoard';
import type { ServiceLines } from '@/components/board/NetworkTile';
import { NetworkUnavailable } from '@/components/scope/NetworkUnavailable';
import { useNetworkFeed } from '@/lib/board/useNetworkFeed';
import { readNetworkView } from '@/lib/network/browser';
import { goneOrganisations } from '@/lib/network/entries';
import { parseDirectory, parsePhones } from '@/lib/network/parse';
import type { NetworkBoard as Board } from '@/lib/network/types';
import { NetworkScope } from './NetworkScope';
import styles from './Network.module.css';

// The network board page (TEN-070): the networks the server offers, then the board of the one, kept
// current from the network's stream, with the service lines the organisations shared. What it is in every
// state is said on the page: not available (no figure), offline (the figures as last known), a stopped
// organisation and a delayed one. No network, tenant or source id is on the page or in its address.

const HISTORY_HREF = '/network/history';
const NETWORK_HREF = '/network/board';

async function readServiceLines(networkId: string): Promise<ServiceLines> {
  const result = await readNetworkView('phones', networkId, (body) => parsePhones(body, 'bff'));
  if (!result.ok) return null;
  return Object.fromEntries(result.data.phones.map((phone) => [phone.rowRef, { label: phone.contactLabel, phone: phone.contactPhone }]));
}

/** When an organisation stopped sharing: the latest end of its entries in the history, or null when it is not there. */
async function stoppedDate(networkId: string, organisation: string): Promise<string | null> {
  const result = await readNetworkView('directory', networkId, (body) => parseDirectory(body, 'bff'), 'history=true');
  if (!result.ok) return null;
  const ended = result.data.entries.filter((entry) => entry.organisationName === organisation && entry.endedAt !== null).map((entry) => entry.endedAt as string);
  return ended.length === 0 ? null : ended.sort().at(-1) ?? null;
}

function Live({ networkId, networkName, ownOrganisation, ownHref }: { networkId: string; networkName: string; ownOrganisation: string | null; ownHref: string }) {
  const feed = useNetworkFeed({ networkId });
  const [lines, setLines] = useState<ServiceLines>(undefined);
  const [stopped, setStopped] = useState<StoppedOrganisation[]>([]);
  const [retry, setRetry] = useState(0);
  const previous = useRef<Board | null>(null);

  const board = feed.status === 'ready' ? feed.board : null;
  const generatedAt = board?.generatedAt ?? null;

  // The service lines are read with each new board (they are the organisations' own, and change rarely).
  useEffect(() => {
    if (generatedAt === null) return;
    let current = true;
    void readServiceLines(networkId).then((read) => {
      if (current) setLines(read);
    });
    return () => {
      current = false;
    };
  }, [networkId, generatedAt]);

  // An organisation that was on the board and is not now stopped sharing: say so until the viewer leaves.
  useEffect(() => {
    if (board === null) return;
    const before = previous.current;
    previous.current = board;
    if (before === null) return;
    const gone = goneOrganisations(before.entries, board.entries);
    if (gone.length === 0) return;
    let current = true;
    void Promise.all(gone.map(async (organisation) => ({ organisation, date: await stoppedDate(networkId, organisation) }))).then((found) => {
      if (current) setStopped((existing) => [...existing.filter((item) => !gone.includes(item.organisation)), ...found].sort((a, b) => a.organisation.localeCompare(b.organisation, 'en-GB')));
    });
    return () => {
      current = false;
    };
  }, [board, networkId]);

  if (feed.status === 'loading') return <main className={styles.page}><p role="status">Loading the network board</p></main>;
  if (feed.status === 'unavailable') return <main className={styles.page}><NetworkUnavailable reason="not-available" ownHref={ownHref} /></main>;
  if (feed.status === 'offline') {
    return (
      <main className={styles.page}>
        <NetworkUnavailable reason="offline" networkName={networkName} ownHref={ownHref} since={feed.since} onRetry={() => setRetry((n) => n + 1)} key={retry} />
      </main>
    );
  }
  return (
    <NetworkBoard
      board={feed.board}
      networkName={networkName}
      ownOrganisation={ownOrganisation}
      serviceLines={lines}
      switchTo={{ ownHref, networkHref: NETWORK_HREF }}
      lastKnown={feed.assessment.mode === 'last-known' ? feed.assessment : undefined}
      onRetry={() => setRetry((n) => n + 1)}
      stopped={stopped}
      historyHref={HISTORY_HREF}
    />
  );
}

export function NetworkBoardView({ ownHref }: { ownHref: string }) {
  return (
    <NetworkScope ownHref={ownHref} networkHref={NETWORK_HREF}>
      {({ network, ownOrganisation }) => <Live networkId={network.id} networkName={network.name} ownOrganisation={ownOrganisation} ownHref={ownHref} />}
    </NetworkScope>
  );
}
