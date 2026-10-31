import { Banner } from '@/components/ui/Banner';
import { Button } from '@/components/ui/Button';
import { londonTime } from '@/lib/board/format';
import { dayText } from '@/lib/network/entries';
import { ScopeHeader } from './ScopeHeader';
import styles from './Scope.module.css';

// The states in which the network is not shown (docs/design/network-ui.md section 5, TEN-070). Every
// refusal reads the same ("Network view not available"), so the words never tell a viewer whether a
// network exists, who is in it or why they cannot see it. The other states name the network and say what
// to do next. Each is announced politely once; none blocks navigation; and where a network is named, the
// scope header stays.

export type UnavailableReason = 'not-available' | 'paused' | 'membership-ended' | 'offline';

const OFFLINE_BODY = 'Figures are the last known and may be wrong. Use the whiteboard and phone process.';

/** The offline banner with its way to try again, as a board that has figures to keep shows it too. */
export function OfflinePanel({ since, onRetry, withFigures }: { since: string; onRetry?: () => void; withFigures: boolean }) {
  return (
    <Banner tone="offline" title={`Network board offline since ${londonTime(since)}`} dataEl="NET-STATE-PANEL">
      <p className={styles.panelBody}>{withFigures ? OFFLINE_BODY : 'There are no figures to show. Use the whiteboard and phone process.'}</p>
      {onRetry !== undefined ? (
        <Button variant="secondary" onClick={onRetry} dataEl="NET-STATE-RETRY-BTN">
          Try again
        </Button>
      ) : null}
    </Banner>
  );
}

export type NetworkUnavailableProps = {
  reason: UnavailableReason;
  /** The network's display name: needed by every state but "not available", which names none. */
  networkName?: string;
  /** The viewer's own board, for the way back. */
  ownHref: string;
  onRetry?: () => void;
  historyHref?: string;
  /** A time, for the day the membership ended or the time the board went offline. */
  endedOn?: string;
  since?: string;
};

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className={styles.panel} role="status" data-el="NET-STATE-PANEL">
      <h1 className={styles.panelTitle}>{title}</h1>
      {children}
    </div>
  );
}

export function NetworkUnavailable({ reason, networkName, ownHref, onRetry, historyHref, endedOn, since }: NetworkUnavailableProps) {
  if (reason === 'not-available') {
    return (
      <Panel title="Network view not available">
        <p className={styles.panelBody}>Ask your administrator.</p>
        <p className={styles.panelBody}>
          <a href={ownHref} data-el="NET-STATE-BACK-LINK">
            Back to our organisation
          </a>
        </p>
      </Panel>
    );
  }

  const name = networkName ?? '';
  return (
    <>
      {/* The header stays wherever a network is named; a read that failed before any name was known has none. */}
      {networkName === undefined ? null : <ScopeHeader scope="network" networkName={name} />}
      {reason === 'paused' ? (
        <Panel title="The network view is paused">
          <p className={styles.panelBody}>{`${name} is not sharing capacity at the moment. Phone services to check.`}</p>
          {onRetry !== undefined ? (
            <Button variant="secondary" onClick={onRetry} dataEl="NET-STATE-RETRY-BTN">
              Try again
            </Button>
          ) : null}
        </Panel>
      ) : null}
      {reason === 'membership-ended' ? (
        <Panel title={`Your organisation has left ${name}`}>
          <p className={styles.panelBody}>{endedOn === undefined ? 'You can see the history of what was shared.' : `You can see the history of what was shared until ${dayText(endedOn)}.`}</p>
          {historyHref !== undefined ? (
            <p className={styles.panelBody}>
              <a href={historyHref} data-el="NET-BOARD-HISTORY-LINK">
                See history
              </a>
            </p>
          ) : null}
        </Panel>
      ) : null}
      {reason === 'offline' ? <OfflinePanel since={since ?? new Date().toISOString()} onRetry={onRetry} withFigures={false} /> : null}
    </>
  );
}
