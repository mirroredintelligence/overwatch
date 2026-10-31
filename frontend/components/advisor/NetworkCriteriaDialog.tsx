'use client';

import { useEffect, useState } from 'react';
import { Button } from '@/components/ui/Button';
import { Dialog } from '@/components/ui/Dialog';
import { NEED_LABELS } from '@/lib/criteria/model';
import type { NeedCode } from '@/lib/criteria/types';
import { readNetworkView } from '@/lib/network/browser';
import { dayText } from '@/lib/network/entries';
import { parseCriteria } from '@/lib/network/parse';
import type { NetworkCriteriaEntry } from '@/lib/network/types';
import styles from './dialog-body.module.css';

// The criteria of ANOTHER organisation's service (docs/design/network-ui.md sections 4 and 9, WB11): the
// current version only, read only. There is no reason for the change, no owner, no review history, and no
// "Report a problem with these criteria": that message would go to an organisation the viewer cannot
// message. The service is the listing's own reference, the network the one the server offered; both are in
// memory, never in an address. A service that shared no criteria says so and says to phone.

const needs = (codes: readonly string[]) => (codes.length === 0 ? 'none listed' : codes.map((code) => NEED_LABELS[code as NeedCode] ?? code).join(', '));

type Load = { kind: 'loading' } | { kind: 'ready'; entry: NetworkCriteriaEntry | null } | { kind: 'failed' };

export function NetworkCriteriaDialog({
  networkId,
  rowRef,
  serviceName,
  organisationName,
  onClose,
}: {
  networkId: string;
  rowRef: string;
  serviceName: string;
  organisationName: string;
  onClose: () => void;
}) {
  const [load, setLoad] = useState<Load>({ kind: 'loading' });

  useEffect(() => {
    let live = true;
    void readNetworkView('criteria', networkId, (body) => parseCriteria(body, 'bff')).then((result) => {
      if (!live) return;
      setLoad(result.ok ? { kind: 'ready', entry: result.data.entries.find((candidate) => candidate.rowRef === rowRef) ?? null } : { kind: 'failed' });
    });
    return () => {
      live = false;
    };
  }, [networkId, rowRef]);

  return (
    <Dialog title={`Criteria: ${serviceName}`} sub="Current version, read only" dataEl="ADV-CRIT-DIALOG" onClose={onClose}>
      <div className={styles.body}>
        <p className={styles.meta}>{`Shared by ${organisationName}`}</p>
        {load.kind === 'loading' ? <p className={styles.text}>Loading the criteria.</p> : null}
        {load.kind === 'failed' ? <p className={styles.error}>The criteria could not be read. Phone the service to check.</p> : null}
        {load.kind === 'ready' && load.entry === null ? <p className={styles.text}>No criteria shared. Phone the service to check.</p> : null}
        {load.kind === 'ready' && load.entry !== null ? (
          <>
            <p className={styles.text}>{`Accepts: ${needs(load.entry.accepts)}`}</p>
            <p className={styles.text}>{`Does not accept: ${needs(load.entry.excludes)}`}</p>
            <p className={styles.text}>{`Ages: ${load.entry.ageMin} to ${load.entry.ageMax}`}</p>
            <p className={styles.text}>{`Districts: ${load.entry.districts.length === 0 ? 'none listed' : load.entry.districts.join(', ')}`}</p>
            <p className={styles.text}>{`Review by ${dayText(`${load.entry.reviewBy}T12:00:00Z`)}`}</p>
          </>
        ) : null}
        <div className={styles.actions}>
          <Button variant="secondary" onClick={onClose}>
            Close
          </Button>
        </div>
      </div>
    </Dialog>
  );
}
