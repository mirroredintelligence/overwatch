'use client';

import { useCallback, useEffect, useState } from 'react';
import { NetworkUnavailable } from '@/components/scope/NetworkUnavailable';
import { ScopeHeader } from '@/components/scope/ScopeHeader';
import { londonTime } from '@/lib/board/format';
import { POLL_INTERVAL_MS } from '@/lib/board/liveness';
import { readNetworkView } from '@/lib/network/browser';
import { NETWORK_ROUTES } from '@/lib/network/links';
import { parseSystemNow } from '@/lib/network/parse';
import type { NetworkSystemNow, SystemNowKey } from '@/lib/network/types';
import { NetworkScope } from './NetworkScope';
import styles from './Network.module.css';
import view from './NetworkSystemNowView.module.css';

// "System now" of the network (W17, network variant, `GET /network/{id}/system-now`): the counts of the
// network board by status, how many services from how many organisations, and the pressure state. A network
// has no chase cards, ladder or requests: those are an organisation's own, so this is the counts and the
// pressure, naming no organisation and no service. The pressure is a state of the board, said as one, never
// an instruction (H-654, DEC-982). A read that fails keeps the last good counts and says so.

// The symbol is drawn by CSS from data-symbol (shape plus word, never colour alone).
const ROWS: [SystemNowKey, string, string][] = [
  ['accepting', 'Accepting', '●'],
  ['limited', 'Limited', '◐'],
  ['not-accepting', 'Not accepting', '■'],
  ['over-capacity', 'Over capacity', '▲'],
  ['not-updated', 'Not updated', '◌'],
  ['out-of-hours', 'Out of hours', ''],
  ['unavailable', 'Not on the network', ''],
];

const FOOTNOTE = "Your organisation's own chase cards, escalation ladder and requests are on your own System now, not here.";

const countWord = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;
const REASON = (n: number) => `${n} ${n === 1 ? 'service is' : 'services are'} limited, not accepting or over capacity.`;
const shareOf = (n: number, total: number) => (total > 0 ? (n / total) * 100 : 0);

type Load = { kind: 'loading' } | { kind: 'ready'; now: NetworkSystemNow; stale: boolean } | { kind: 'refused' } | { kind: 'failed' };

// One stacked bar of every status, sized by its count. The image name carries every status and its number.
function StackedBar({ now }: { now: NetworkSystemNow }) {
  const name = `Of ${countWord(now.services, 'service', 'services')}: ${ROWS.map(([key, word]) => `${now.byStatus[key]} ${word.toLowerCase()}`).join(', ')}`;
  return (
    <div role="img" aria-label={name} className={view.stack}>
      {ROWS.filter(([key]) => now.byStatus[key] > 0).map(([key]) => (
        <span key={key} data-status={key} data-css={JSON.stringify({ flexGrow: now.byStatus[key] })} />
      ))}
    </div>
  );
}

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

  if (load.kind === 'refused') return <main className={view.page}><NetworkUnavailable reason="not-available" ownHref={ownHref} /></main>;

  const now = load.kind === 'ready' ? load.now : null;
  const pressure = now === null
    ? null
    : now.alert.raised
      ? { title: 'Network pressure is high.', when: `High from ${now.alert.highFrom}.` }
      : now.alert.level === 'watch'
        ? { title: 'Network pressure is rising.', when: `Rising from ${now.alert.watchFrom}.` }
        : null;

  return (
    <main className={view.page}>
      <h1 className={styles.title}>{`${networkName} system now`}</h1>
      <ScopeHeader scope="network" networkName={networkName} switchTo={{ ownHref, networkHref: NETWORK_ROUTES['system-now'] }} />
      {load.kind === 'loading' ? <p role="status" className={view.meta}>Loading the network</p> : null}
      {load.kind === 'failed' || (load.kind === 'ready' && load.stale) ? <p role="alert" className={view.alert}>The network could not be read. Try again shortly.</p> : null}
      {now !== null ? (
        <div className={view.layout}>
          <div className={view.column}>
            {pressure !== null ? (
              <div className={view.notice}>
                <b>{pressure.title}</b>{` ${REASON(now.alert.limitedOrWorse)} ${pressure.when}`}
              </div>
            ) : null}
            <div className={view.card}>
              <div className={view.cardHead}>
                <h2 className={view.eyebrow}>Services by status</h2>
                <p className={view.meta}>
                  <span>{`${countWord(now.services, 'service', 'services')} from ${countWord(now.organisations, 'organisation', 'organisations')}`}</span>
                  {' · '}
                  <span>{load.kind === 'ready' && load.stale ? `Last known ${londonTime(now.generatedAt)}` : `As at ${londonTime(now.generatedAt)}`}</span>
                </p>
              </div>
              <div role="group" aria-label="Services by status" className={view.group}>
                <StackedBar now={now} />
                <dl className={view.rows}>
                  {ROWS.map(([key, word, symbol]) => (
                    <div key={key} className={view.row}>
                      <dt data-symbol={symbol}>{word}</dt>
                      <dd className={view.count}>{now.byStatus[key]}</dd>
                      <dd className={view.track} aria-hidden="true">
                        <i data-status={key} data-css={JSON.stringify({ width: `${shareOf(now.byStatus[key], now.services)}%` })} />
                      </dd>
                    </div>
                  ))}
                </dl>
              </div>
            </div>
          </div>
          <div className={view.column}>
            <div className={view.card}>
              <h2 className={view.eyebrow}>What this is</h2>
              <p className={view.body}>The counts of the network board and the state of its pressure. It names no organisation and no service.</p>
              <p className={view.muted}>Pressure is a state of the board, said as one. It is never an instruction.</p>
            </div>
            <div className={`${view.card} ${view.dashed}`}>
              <h2 className={view.eyebrow}>If the network cannot be read</h2>
              <p className={view.body}>The last good counts stay, marked Last known, with the message &quot;The network could not be read. Try again shortly.&quot; Zeros are never shown for a failed read.</p>
            </div>
            <p className={view.footnote}>{FOOTNOTE}</p>
          </div>
        </div>
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
