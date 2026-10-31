'use client';

import { useCallback, useEffect, useState, type ReactNode } from 'react';
import { NetworkUnavailable } from '@/components/scope/NetworkUnavailable';
import type { ScopeLinks } from '@/components/scope/ScopeSwitch';
import { Chip } from '@/components/ui/Chip';
import { readNetworkList } from '@/lib/network/browser';
import type { NetworkList, NetworkSummary } from '@/lib/network/types';
import styles from './Network.module.css';

// The gate every network page stands in (TEN-068, TEN-070). It reads the networks the server offers this
// viewer (the registry's answer, per call) and shows the page only for one of them. Any refusal is the one
// "not available" panel, so the words never say whether a network exists; a read that fails is "offline"
// with a way to try again. With more than one network the viewer chooses in the page, never in the
// address, and the page below is started afresh for the one chosen (so one network's figures are never
// shown as another's).

export type NetworkScopeContext = {
  network: NetworkSummary;
  ownOrganisation: string | null;
  /** The two routes of the scope switch: the viewer's own page, and this network page. */
  switchTo: ScopeLinks;
};

type Load = { kind: 'loading' } | { kind: 'ready'; list: NetworkList } | { kind: 'refused' } | { kind: 'failed'; since: string };

export function NetworkScope({ ownHref, networkHref, children }: ScopeLinks & { children: (context: NetworkScopeContext) => ReactNode }) {
  const [load, setLoad] = useState<Load>({ kind: 'loading' });
  const [chosenId, setChosenId] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let current = true;
    void (async () => {
      const result = await readNetworkList();
      if (!current) return;
      if (result.ok) setLoad({ kind: 'ready', list: result.data });
      else if ([401, 403, 404].includes(result.status)) setLoad({ kind: 'refused' });
      else setLoad((previous) => (previous.kind === 'failed' ? previous : { kind: 'failed', since: new Date().toISOString() }));
    })();
    return () => {
      current = false;
    };
  }, [attempt]);

  const retry = useCallback(() => {
    setLoad({ kind: 'loading' });
    setAttempt((n) => n + 1);
  }, []);

  if (load.kind === 'loading') {
    return (
      <main className={styles.page}>
        <p role="status">Loading the network</p>
      </main>
    );
  }
  if (load.kind === 'refused' || (load.kind === 'ready' && load.list.networks.length === 0)) {
    return (
      <main className={styles.page}>
        <NetworkUnavailable reason="not-available" ownHref={ownHref} />
      </main>
    );
  }
  if (load.kind === 'failed') {
    return (
      <main className={styles.page}>
        <NetworkUnavailable reason="offline" ownHref={ownHref} onRetry={retry} since={load.since} />
      </main>
    );
  }

  const { networks, ownOrganisation } = load.list;
  const network = networks.find((candidate) => candidate.id === chosenId) ?? networks[0]!;
  return (
    <>
      {networks.length > 1 ? (
        <div className={styles.chooser} role="group" aria-label="Which network">
          {networks.map((candidate) => (
            <Chip key={candidate.id} pressed={candidate.id === network.id} onPressedChange={() => setChosenId(candidate.id)}>
              {candidate.name}
            </Chip>
          ))}
        </div>
      ) : null}
      <div key={network.id}>{children({ network, ownOrganisation, switchTo: { ownHref, networkHref } })}</div>
    </>
  );
}
