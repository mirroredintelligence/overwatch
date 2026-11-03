'use client';

import { useRef, useState } from 'react';
import { Button } from '@/components/ui/Button';
import { Dialog } from '@/components/ui/Dialog';
import { leadPut, newIdempotencyKey } from '@/lib/lead/browser';
import { boardChangedFrom, type BoardChanged, type ChoosableNetwork, type ScreenRow } from '@/lib/screens/admin';
import styles from './ScreenList.module.css';

// Which board a wall screen shows (docs/design/network-ui.md section 6, ScreenBoardChoice, TEN-072): the
// organisation's own, or a network it is an active member of. The networks are the ones the back end
// offered in the list: the page never sends one it was not offered (and the BFF and the back end check the
// membership again). The screen's version goes back as `If-Match`, so a change made by someone else in the
// meantime is a 412 and not an overwrite. One key per dialog: a second try of the same choice is one change.
// The words say when the screen picks it up and that its own header always says which board it shows.

export type BoardOutcome = { kind: 'saved'; changed: BoardChanged; choice: string } | { kind: 'stale' } | { kind: 'gone' } | { kind: 'ended' };

const OWN = 'tenant';

export function ScreenBoardChoice({
  row,
  networks,
  onClose,
  onResult,
}: {
  row: ScreenRow;
  networks: ChoosableNetwork[];
  onClose: () => void;
  onResult: (outcome: BoardOutcome) => void;
}) {
  // A screen set to a network it can no longer read shows the organisation's own board: it starts there.
  const showingNetwork = row.boardScope === 'network' && row.networkAvailable ? row.networkId : null;
  const start = showingNetwork !== null && networks.some((network) => network.id === showingNetwork) ? showingNetwork : OWN;
  const [chosen, setChosen] = useState<string>(start);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const key = useRef<string>(newIdempotencyKey());
  const sending = useRef(false);
  const closed = row.boardScope === 'network' && !row.networkAvailable;

  async function save() {
    if (sending.current) return;
    const network = networks.find((item) => item.id === chosen);
    // Only a board the server offered is ever sent.
    if (chosen !== OWN && network === undefined) return;
    sending.current = true;
    setBusy(true);
    setFailed(false);
    const body = network === undefined ? { boardScope: 'tenant' } : { boardScope: 'network', networkId: network.id };
    const result = await leadPut(`/api/bff/screens/${encodeURIComponent(row.deviceId)}/board-scope`, body, {
      idempotencyKey: key.current,
      ifMatch: `W/"${row.scopeVersion}"`,
    });
    sending.current = false;
    setBusy(false);
    if (result.ok) {
      try {
        onResult({ kind: 'saved', changed: boardChangedFrom(result.body), choice: network === undefined ? 'Our organisation' : `Network, ${network.name}` });
      } catch {
        setFailed(true);
      }
    } else if (result.status === 412 || result.status === 428) onResult({ kind: 'stale' });
    else if (result.status === 404) onResult({ kind: 'gone' });
    else if (result.status === 401 || result.status === 403) onResult({ kind: 'ended' });
    else setFailed(true);
  }

  return (
    <Dialog title={`Which board does ${row.name} show?`} dataEl="SCREENS-BOARD-DIALOG" onClose={onClose}>
      <div className={styles.dialogBody}>
        <fieldset className={styles.group}>
          <legend className={styles.legend}>Board</legend>
          <label className={styles.radioRow}>
            <input type="radio" name="board" value={OWN} checked={chosen === OWN} onChange={() => setChosen(OWN)} data-el="SCREENS-BOARD-OWN-RADIO" />
            Our organisation
          </label>
          {networks.map((network) => (
            <label key={network.id} className={styles.radioRow}>
              <input type="radio" name="board" value={network.id} checked={chosen === network.id} onChange={() => setChosen(network.id)} data-el="SCREENS-BOARD-NETWORK-RADIO" />
              {`Network, ${network.name}`}
            </label>
          ))}
        </fieldset>
        {networks.length === 0 ? <p className={styles.dialogNote}>Your organisation is not in a network.</p> : null}
        {closed ? (
          <p className={styles.dialogNote}>
            {`This screen is set to Network, ${row.networkName ?? 'a network'}, which your organisation can no longer see. It shows Our organisation.`}
          </p>
        ) : null}
        <p className={styles.dialogNote}>The screen changes the next time it refreshes. Its header always says which board it shows.</p>
        {failed ? (
          <p role="alert" className={styles.dialogError}>
            The board could not be changed. Try again.
          </p>
        ) : null}
        <div className={styles.dialogActions}>
          <Button variant="neutral" onClick={onClose} dataEl="SCREENS-BOARD-CANCEL-BTN">
            Cancel
          </Button>
          <Button variant="primary" busy={busy} disabled={chosen === start} onClick={() => void save()} dataEl="SCREENS-BOARD-SAVE-BTN">
            Save
          </Button>
        </div>
      </div>
    </Dialog>
  );
}
