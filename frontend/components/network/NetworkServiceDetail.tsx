'use client';

import { useEffect, useState } from 'react';
import { NetworkUnavailable } from '@/components/scope/NetworkUnavailable';
import { ReadOnlyNote } from '@/components/scope/ReadOnlyNote';
import { ScopeHeader } from '@/components/scope/ScopeHeader';
import { categoryLabel } from '@/lib/board/format';
import { NEED_LABELS } from '@/lib/criteria/model';
import type { NeedCode } from '@/lib/criteria/types';
import { readNetworkView } from '@/lib/network/browser';
import { dayText } from '@/lib/network/entries';
import { hoursText } from '@/lib/network/hours';
import { NETWORK_ROUTES } from '@/lib/network/links';
import { ownRow } from '@/lib/network/orgs';
import { parseCriteria, parseDirectory } from '@/lib/network/parse';
import type { NetworkCriteriaEntry, NetworkDirectoryEntry } from '@/lib/network/types';
import { NetworkScope } from './NetworkScope';
import styles from './Network.module.css';

// One service of the network (docs/design/network-ui.md, NetworkServiceDetail, TEN-071), read only: about
// it, its hours, its service line and its CURRENT criteria. There is no reason, no owner, no version and no
// history, and no way to report a problem with the criteria (that message would go to an organisation the
// viewer cannot message). The service is named by the opaque row reference of the address.

const needs = (codes: readonly string[]) => (codes.length === 0 ? 'none listed' : codes.map((code) => NEED_LABELS[code as NeedCode] ?? code).join(', '));

type Load =
  | { kind: 'loading' }
  | { kind: 'ready'; entry: NetworkDirectoryEntry; criteria: NetworkCriteriaEntry | null | 'unreadable' }
  | { kind: 'refused' };

function Detail({ networkId, networkName, ownOrganisation, ownHref, rowRef }: { networkId: string; networkName: string; ownOrganisation: string | null; ownHref: string; rowRef: string }) {
  const [load, setLoad] = useState<Load>({ kind: 'loading' });

  useEffect(() => {
    let current = true;
    void (async () => {
      const [directory, criteria] = await Promise.all([
        readNetworkView('directory', networkId, (body) => parseDirectory(body, 'bff')),
        readNetworkView('criteria', networkId, (body) => parseCriteria(body, 'bff')),
      ]);
      if (!current) return;
      const entry = directory.ok ? directory.data.entries.find((candidate) => candidate.rowRef === rowRef && candidate.active) : undefined;
      // A refusal, a failure to read the directory and a service that is not there are the one panel.
      if (entry === undefined) return setLoad({ kind: 'refused' });
      setLoad({ kind: 'ready', entry, criteria: criteria.ok ? (criteria.data.entries.find((candidate) => candidate.rowRef === rowRef) ?? null) : 'unreadable' });
    })();
    return () => {
      current = false;
    };
  }, [networkId, rowRef]);

  if (load.kind === 'refused') return <main className={styles.page}><NetworkUnavailable reason="not-available" ownHref={ownHref} /></main>;
  if (load.kind === 'loading') return <main className={styles.page}><p role="status">Loading the service</p></main>;

  const { entry, criteria } = load;
  const where = [categoryLabel(entry.category), entry.location?.name ?? null, entry.location?.postalDistrict ?? null].filter((part): part is string => part !== null).join(' · ');
  return (
    <main className={styles.page}>
      <h1 className={styles.title}>{entry.serviceName}</h1>
      <ScopeHeader scope="network" networkName={networkName} switchTo={{ ownHref, networkHref: NETWORK_ROUTES.services }} />
      <p>
        <a href={NETWORK_ROUTES.services}>All network services</a>
      </p>
      <ReadOnlyNote />

      <section className={styles.row} aria-labelledby="net-about">
        <h2 id="net-about" className={styles.rowTitle}>About this service</h2>
        <p>{`Shared by ${entry.organisationName}`}</p>
        {ownRow(entry.organisationName, ownOrganisation) ? <p className={styles.muted}>Your organisation</p> : null}
        <p className={styles.muted}>{where}</p>
        <p className={styles.muted}>{entry.source === 'manual' ? 'Entered by the organisation' : 'From the Directory of Services'}</p>
        {entry.presentation === 'unavailable' ? <p>Not available on the network. Phone to confirm.</p> : null}
      </section>

      <section className={styles.row} aria-labelledby="net-hours">
        <h2 id="net-hours" className={styles.rowTitle}>Opening hours</h2>
        <p>{hoursText(entry.openingHours)}</p>
      </section>

      <section className={styles.row} aria-labelledby="net-line">
        <h2 id="net-line" className={styles.rowTitle}>Service line</h2>
        {entry.contactPhone === null ? (
          <p>No number shared</p>
        ) : (
          <>
            <p>{`${entry.contactLabel ?? 'Service line'} ${entry.contactPhone}`}</p>
            <p>
              <a href={`tel:${entry.contactPhone.replace(/[^0-9+]/g, '')}`} data-el="NET-BOARD-PHONE-LINK">{`Phone ${entry.serviceName} on ${entry.contactPhone}`}</a>
            </p>
          </>
        )}
      </section>

      <section className={styles.row} aria-labelledby="net-criteria" data-el="NET-SERVICE-CRITERIA-SECTION">
        <h2 id="net-criteria" className={styles.rowTitle}>Criteria</h2>
        {criteria === 'unreadable' ? (
          <p>The criteria could not be read. Phone to confirm.</p>
        ) : criteria === null ? (
          <p>No criteria shared</p>
        ) : (
          <>
            <p>{`Accepts: ${needs(criteria.accepts)}`}</p>
            <p>{`Does not accept: ${needs(criteria.excludes)}`}</p>
            <p>{`Ages: ${criteria.ageMin} to ${criteria.ageMax}`}</p>
            <p>{`Districts: ${criteria.districts.length === 0 ? 'none listed' : criteria.districts.join(', ')}`}</p>
            <p>{`Review by ${dayText(`${criteria.reviewBy}T12:00:00Z`)}`}</p>
          </>
        )}
      </section>
    </main>
  );
}

export function NetworkServiceDetail({ rowRef, ownHref }: { rowRef: string; ownHref: string }) {
  return (
    <NetworkScope ownHref={ownHref} networkHref={NETWORK_ROUTES.services}>
      {({ network, ownOrganisation }) => <Detail networkId={network.id} networkName={network.name} ownOrganisation={ownOrganisation} ownHref={ownHref} rowRef={rowRef} />}
    </NetworkScope>
  );
}
