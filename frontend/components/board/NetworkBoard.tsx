'use client';

import { useState } from 'react';
import { OfflinePanel } from '@/components/scope/NetworkUnavailable';
import { ReadOnlyNote } from '@/components/scope/ReadOnlyNote';
import { ScopeHeader } from '@/components/scope/ScopeHeader';
import { ScopeNotice } from '@/components/scope/ScopeNotice';
import type { ScopeLinks } from '@/components/scope/ScopeSwitch';
import { Chip } from '@/components/ui/Chip';
import { dayText, delayedOrganisations } from '@/lib/network/entries';
import { organisationsOf, ownRow } from '@/lib/network/orgs';
import type { NetworkBoard as BoardData } from '@/lib/network/types';
import type { LastKnown } from './LastKnownBanner';
import styles from './Board.module.css';
import { NetworkRow, NetworkTile, type ServiceLines } from './NetworkTile';

// The network capacity board (docs/design/network-ui.md section 4, TEN-070): every organisation's services
// that the network shares, read only, in the order the back end sent them (category, organisation, service:
// never ranked, never re-sorted here). The page says which board it is, labels each row with its
// organisation and marks the viewer's own in words. It takes what it is given and sends nothing: the
// organisation filter and the view toggle work over the rows it already has.

export type StoppedOrganisation = { organisation: string; date: string | null };

export type NetworkBoardProps = {
  board: BoardData;
  networkName: string;
  /** The viewer's own organisation's display name, to mark its rows; null when not known. */
  ownOrganisation: string | null;
  /** Undefined while they are being read. */
  serviceLines?: ServiceLines;
  switchTo?: ScopeLinks;
  /** Set when the board must be shown as last known: never styled or worded as current. */
  lastKnown?: LastKnown;
  onRetry?: () => void;
  /** Organisations that were on the board and have stopped sharing, with the day when it is known. */
  stopped?: StoppedOrganisation[];
  historyHref?: string;
};

const countWord = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

export function NetworkBoard({ board, networkName, ownOrganisation, serviceLines, switchTo, lastKnown, onRetry, stopped = [], historyHref }: NetworkBoardProps) {
  const [chosen, setChosen] = useState<string | null>(null);
  const [layout, setLayout] = useState<'tiles' | 'list'>('tiles');

  const now = lastKnown ? lastKnown.now : board.generatedAt;
  const organisations = organisationsOf(board.entries.map((entry) => entry.organisationName), ownOrganisation);
  const refOf = new Map(organisations.map((organisation) => [organisation.name, organisation.ref]));
  const visible = chosen === null ? board.entries : board.entries.filter((entry) => entry.organisationName === chosen);
  const delayed = lastKnown ? [] : delayedOrganisations(board.entries);
  const dated = stopped.filter((item) => item.date !== null);

  return (
    <main className={styles.board}>
      <header className={styles.header}>
        <h1 className={styles.title}>{`${networkName} capacity`}</h1>
      </header>

      <ScopeHeader scope="network" networkName={networkName} switchTo={switchTo} />

      {lastKnown ? <OfflinePanel since={lastKnown.since} onRetry={onRetry} withFigures /> : null}

      {stopped.length > 0 ? (
        <ScopeNotice tone="info" title={`No longer shown: ${stopped.map((item) => item.organisation).join(', ')}.`}>
          {dated.map((item) => (
            <p key={item.organisation}>{`${item.organisation} stopped sharing on ${dayText(item.date as string)}.`}</p>
          ))}
          {historyHref !== undefined ? (
            <p>
              <a href={historyHref} data-el="NET-BOARD-HISTORY-LINK">
                See history
              </a>
            </p>
          ) : null}
        </ScopeNotice>
      ) : null}

      {delayed.map((name) => (
        <ScopeNotice key={name} tone="warning" title={`Updates from ${name} are delayed. Its services show Not updated.`} />
      ))}

      <ReadOnlyNote />

      {board.entries.length === 0 ? (
        <div className={styles.empty} role="status">
          <p>No services are shared yet</p>
          <p>{`When organisations share their capacity with ${networkName}, their services appear here.`}</p>
        </div>
      ) : (
        <>
          <p className={styles.note}>
            {`${countWord(board.entries.length, 'service', 'services')} from ${countWord(organisations.length, 'organisation', 'organisations')}`}
          </p>

          <div className={styles.controls}>
            <div className={styles.chips} role="group" aria-label="Organisations">
              <Chip pressed={chosen === null} onPressedChange={() => setChosen(null)} dataEl="NET-BOARD-ORG-ALL-CHIP">
                All organisations
              </Chip>
              {organisations.map((organisation) => (
                <Chip
                  key={organisation.ref}
                  pressed={chosen === organisation.name}
                  onPressedChange={(next) => setChosen(next ? organisation.name : null)}
                  dataEl="NET-BOARD-ORG-CHIP"
                  data={{ 'data-org-ref': organisation.ref }}
                >
                  {organisation.name}
                </Chip>
              ))}
            </div>
            <div className={styles.chips} role="group" aria-label="How to show the services">
              <Chip pressed={layout === 'tiles'} onPressedChange={() => setLayout('tiles')} dataEl="NET-BOARD-VIEW-GRID-BTN">
                Tiles
              </Chip>
              <Chip pressed={layout === 'list'} onPressedChange={() => setLayout('list')} dataEl="NET-BOARD-VIEW-LIST-BTN">
                List
              </Chip>
            </div>
          </div>

          {serviceLines === null ? <p className={styles.note}>Service line numbers could not be loaded. Phone to confirm.</p> : null}

          {visible.length === 0 ? (
            <div className={styles.empty} role="status">
              <p>No services match this filter</p>
              <p>Clear the filter to see all organisations.</p>
            </div>
          ) : (
            <ul className={layout === 'tiles' ? styles.grid : styles.list} aria-label="Services">
              {visible.map((entry) => {
                const common = {
                  entry,
                  now,
                  own: ownRow(entry.organisationName, ownOrganisation),
                  orgRef: refOf.get(entry.organisationName) ?? 'org-0',
                  lines: serviceLines,
                  lastKnown: lastKnown !== undefined,
                };
                return (
                  <li key={entry.rowRef} className={styles.cell}>
                    {layout === 'tiles' ? <NetworkTile {...common} /> : <NetworkRow {...common} />}
                  </li>
                );
              })}
            </ul>
          )}
        </>
      )}

      <footer className={styles.footer}>
        <p className={styles.privacy}>Figures are reported by each organisation. Sorted by category, then organisation. Not ranked.</p>
        <p className={styles.privacy}>No patient information on this screen</p>
      </footer>
    </main>
  );
}
