'use client';

import { useEffect, useState } from 'react';
import { NetworkServiceCard } from '@/components/scope/NetworkServiceCard';
import { NetworkUnavailable } from '@/components/scope/NetworkUnavailable';
import { ReadOnlyNote } from '@/components/scope/ReadOnlyNote';
import { ScopeHeader } from '@/components/scope/ScopeHeader';
import { Chip } from '@/components/ui/Chip';
import { categoryLabel } from '@/lib/board/format';
import { readNetworkView } from '@/lib/network/browser';
import { NETWORK_ROUTES } from '@/lib/network/links';
import { organisationsOf, ownRow } from '@/lib/network/orgs';
import { parseDirectory } from '@/lib/network/parse';
import type { NetworkDirectoryEntry } from '@/lib/network/types';
import { NetworkScope } from './NetworkScope';
import styles from './Network.module.css';

// The network directory (docs/design/network-ui.md, NetworkServices, TEN-071): every member's services the
// network shares, read only, with an organisation filter and a category filter that work over the rows it
// already has. A service its organisation has set inactive is not listed. No action but the link to a
// service's detail.

type Load = { kind: 'loading' } | { kind: 'ready'; entries: NetworkDirectoryEntry[] } | { kind: 'refused' } | { kind: 'failed' };

const countWord = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

function Directory({ networkId, networkName, ownOrganisation, ownHref }: { networkId: string; networkName: string; ownOrganisation: string | null; ownHref: string }) {
  const [load, setLoad] = useState<Load>({ kind: 'loading' });
  const [organisation, setOrganisation] = useState<string | null>(null);
  const [category, setCategory] = useState<string | null>(null);

  useEffect(() => {
    let current = true;
    void readNetworkView('directory', networkId, (body) => parseDirectory(body, 'bff')).then((result) => {
      if (!current) return;
      if (result.ok) setLoad({ kind: 'ready', entries: result.data.entries.filter((entry) => entry.active) });
      else if ([401, 403, 404].includes(result.status)) setLoad({ kind: 'refused' });
      else setLoad({ kind: 'failed' });
    });
    return () => {
      current = false;
    };
  }, [networkId]);

  if (load.kind === 'refused') return <main className={styles.page}><NetworkUnavailable reason="not-available" ownHref={ownHref} /></main>;

  const entries = load.kind === 'ready' ? load.entries : [];
  const organisations = organisationsOf(entries.map((entry) => entry.organisationName), ownOrganisation);
  const refOf = new Map(organisations.map((o) => [o.name, o.ref]));
  const categories = [...new Set(entries.map((entry) => entry.category))];
  const visible = entries.filter((entry) => (organisation === null || entry.organisationName === organisation) && (category === null || entry.category === category));

  return (
    <main className={styles.page}>
      <h1 className={styles.title}>{`${networkName} services`}</h1>
      <ScopeHeader scope="network" networkName={networkName} switchTo={{ ownHref, networkHref: NETWORK_ROUTES.services }} />
      <ReadOnlyNote />
      {load.kind === 'loading' ? <p role="status">Loading the services</p> : null}
      {load.kind === 'failed' ? <p role="alert">The services could not be read. Try again shortly.</p> : null}
      {load.kind === 'ready' && entries.length === 0 ? (
        <div role="status">
          <p>No services are shared yet</p>
          <p>{`When organisations share their capacity with ${networkName}, their services appear here.`}</p>
        </div>
      ) : null}
      {load.kind === 'ready' && entries.length > 0 ? (
        <>
          <p className={styles.muted}>{`${countWord(entries.length, 'service', 'services')} from ${countWord(organisations.length, 'organisation', 'organisations')}`}</p>
          <div className={styles.chips} role="group" aria-label="Organisations">
            <Chip pressed={organisation === null} onPressedChange={() => setOrganisation(null)} dataEl="NET-SERVICES-ORG-CHIP">
              All organisations
            </Chip>
            {organisations.map((o) => (
              <Chip key={o.ref} pressed={organisation === o.name} onPressedChange={(next) => setOrganisation(next ? o.name : null)} dataEl="NET-SERVICES-ORG-CHIP" data={{ 'data-org-ref': o.ref }}>
                {o.name}
              </Chip>
            ))}
          </div>
          <div className={styles.chips} role="group" aria-label="Categories">
            {categories.map((code) => (
              <Chip key={code} pressed={category === code} onPressedChange={(next) => setCategory(next ? code : null)} dataEl="NET-SERVICES-CATEGORY-CHIP">
                {categoryLabel(code)}
              </Chip>
            ))}
          </div>
          {visible.length === 0 ? (
            <div role="status">
              <p>No services match this filter</p>
              <p>Clear the filter to see all organisations.</p>
            </div>
          ) : (
            <ul className={styles.list} aria-label="Services">
              {visible.map((entry) => (
                <NetworkServiceCard key={entry.rowRef} entry={entry} own={ownRow(entry.organisationName, ownOrganisation)} orgRef={refOf.get(entry.organisationName) ?? 'org-0'} />
              ))}
            </ul>
          )}
        </>
      ) : null}
    </main>
  );
}

export function NetworkServicesView({ ownHref }: { ownHref: string }) {
  return (
    <NetworkScope ownHref={ownHref} networkHref={NETWORK_ROUTES.services}>
      {({ network, ownOrganisation }) => <Directory networkId={network.id} networkName={network.name} ownOrganisation={ownOrganisation} ownHref={ownHref} />}
    </NetworkScope>
  );
}
