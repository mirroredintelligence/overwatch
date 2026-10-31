'use client';

import { useCallback, useEffect, useState } from 'react';
import { NetworkWeek } from '@/components/exec/NetworkWeek';
import { NetworkUnavailable } from '@/components/scope/NetworkUnavailable';
import { ScopeHeader } from '@/components/scope/ScopeHeader';
import { Button } from '@/components/ui/Button';
import { readNetworkView } from '@/lib/network/browser';
import { NETWORK_ROUTES } from '@/lib/network/links';
import { parseWeek } from '@/lib/network/parse';
import type { NetworkWeek as Week } from '@/lib/network/types';
import { addWeeks, lastCompleteWeekStart } from '@/lib/network/week';
import { NetworkScope } from './NetworkScope';
import styles from './Network.module.css';

// The network week page (TEN-082): the last complete week, by its Monday, with an earlier week and a later
// one, never past the last complete one. Only the executive and the shift lead read it; for any other role
// the BFF refuses, and the page says the view is not available.

type Load = { kind: 'loading' } | { kind: 'ready'; week: Week } | { kind: 'refused' } | { kind: 'failed' };

function WeekPage({ networkId, networkName, ownHref }: { networkId: string; networkName: string; ownHref: string }) {
  const [latest] = useState(() => lastCompleteWeekStart(new Date()));
  const [start, setStart] = useState(latest);
  const [load, setLoad] = useState<Load>({ kind: 'loading' });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let current = true;
    void readNetworkView('week', networkId, (body) => parseWeek(body, 'bff'), `weekStart=${start}`).then((result) => {
      if (!current) return;
      if (result.ok) setLoad({ kind: 'ready', week: result.data });
      else if ([401, 403, 404].includes(result.status)) setLoad({ kind: 'refused' });
      else setLoad({ kind: 'failed' });
    });
    return () => {
      current = false;
    };
  }, [networkId, start, attempt]);

  const move = useCallback((weeks: number) => {
    setLoad({ kind: 'loading' });
    setStart((from) => addWeeks(from, weeks));
  }, []);

  if (load.kind === 'refused') return <main className={styles.page}><NetworkUnavailable reason="not-available" ownHref={ownHref} /></main>;

  return (
    <main className={styles.page}>
      <ScopeHeader scope="network" networkName={networkName} switchTo={{ ownHref, networkHref: NETWORK_ROUTES.week }} />
      <div className={styles.controls}>
        <Button variant="secondary" onClick={() => move(-1)}>
          Earlier week
        </Button>
        <Button variant="secondary" disabled={start >= latest} onClick={() => move(1)}>
          Later week
        </Button>
      </div>
      {load.kind === 'loading' ? <p role="status">Loading the week</p> : null}
      {load.kind === 'failed' ? (
        <div>
          <p role="alert">This week could not be read. Try again shortly.</p>
          <Button
            variant="secondary"
            onClick={() => {
              setLoad({ kind: 'loading' });
              setAttempt((n) => n + 1);
            }}
          >
            Try again
          </Button>
        </div>
      ) : null}
      {load.kind === 'ready' ? <NetworkWeek week={load.week} networkName={networkName} /> : null}
    </main>
  );
}

export function NetworkWeekView({ ownHref }: { ownHref: string }) {
  return (
    <NetworkScope ownHref={ownHref} networkHref={NETWORK_ROUTES.week}>
      {({ network }) => <WeekPage networkId={network.id} networkName={network.name} ownHref={ownHref} />}
    </NetworkScope>
  );
}
