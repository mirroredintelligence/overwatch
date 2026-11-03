'use client';

import { useEffect, useState } from 'react';
import { NetworkServiceCard } from '@/components/scope/NetworkServiceCard';
import { NetworkUnavailable } from '@/components/scope/NetworkUnavailable';
import { ReadOnlyNote } from '@/components/scope/ReadOnlyNote';
import { ScopeHeader } from '@/components/scope/ScopeHeader';
import { Chip } from '@/components/ui/Chip';
import { Loading, SkeletonRows } from '@/components/ui/Skeleton';
import { StageArea, StageGrid, StageLayer } from '@/components/ui/StageGrid';
import { categoryLabel } from '@/lib/board/format';
import { NEED_LABELS } from '@/lib/criteria/model';
import type { NeedCode } from '@/lib/criteria/types';
import { readNetworkView } from '@/lib/network/browser';
import { agesText, dayText } from '@/lib/network/entries';
import { hoursText } from '@/lib/network/hours';
import { NETWORK_ROUTES } from '@/lib/network/links';
import { organisationsOf, ownRow } from '@/lib/network/orgs';
import { parseCriteria, parseDirectory } from '@/lib/network/parse';
import type { NetworkCriteriaEntry, NetworkDirectoryEntry } from '@/lib/network/types';
import { NetworkScope } from './NetworkScope';
import styles from './NetworkServices.module.css';

// The network directory (docs/design/network-ui.md, NetworkServices and NetworkServiceDetail, TEN-071; the
// board NServices): every member's services the network shares, read only, with an organisation filter and a
// category filter that work over the rows it already has. A service its organisation has set inactive is not
// listed. The list stays on the page when a service is open: the open service sits beside it, in the stage,
// and a service that is not in the directory is the one "not available" panel in that place. No action but
// the link to a service's detail, and no reason, owner, version or history of any criteria.

type Load = { kind: 'loading' } | { kind: 'ready'; entries: NetworkDirectoryEntry[] } | { kind: 'refused' } | { kind: 'failed' };

const countWord = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;
const needs = (codes: readonly string[]) => (codes.length === 0 ? 'none listed' : codes.map((code) => NEED_LABELS[code as NeedCode] ?? code).join(', '));

// The board's two stages: the list alone, then the list at 440px with the open service beside it.
const STAGE_TEMPLATES = ['minmax(0, 1fr) 0px 0px', 'minmax(0, 440px) minmax(0, 1fr) 0px'];
const STAGE_GAPS = ['0px', 'var(--space-5)'];

// One service, open beside the list. Its entry comes from the list; this reads only its CURRENT criteria.
// There is no reason, no owner, no version and no history, and no way to report a problem with the criteria
// (that message would go to an organisation the viewer cannot message).
type CriteriaLoad = { kind: 'loading' } | { kind: 'ready'; criteria: NetworkCriteriaEntry | null | 'unreadable' };

function ServicePane({ networkId, entry, ownOrganisation }: { networkId: string; entry: NetworkDirectoryEntry; ownOrganisation: string | null }) {
  const [load, setLoad] = useState<CriteriaLoad>({ kind: 'loading' });
  const { rowRef } = entry;

  useEffect(() => {
    let current = true;
    void readNetworkView('criteria', networkId, (body) => parseCriteria(body, 'bff')).then((result) => {
      if (!current) return;
      setLoad({ kind: 'ready', criteria: result.ok ? (result.data.entries.find((candidate) => candidate.rowRef === rowRef) ?? null) : 'unreadable' });
    });
    return () => {
      current = false;
    };
  }, [networkId, rowRef]);

  const where = [categoryLabel(entry.category), entry.location?.name ?? null, entry.location?.postalDistrict ?? null].filter((part): part is string => part !== null).join(' · ');
  const own = ownRow(entry.organisationName, ownOrganisation);

  return (
    <div className={styles.card} data-el="NET-SERVICE-DETAIL">
      <p className={styles.back}>
        <a href={NETWORK_ROUTES.services}>All network services</a>
      </p>
      <div className={styles.head}>
        <h2 className={styles.name}>{entry.serviceName}</h2>
        {own ? <span className={styles.own}>Your organisation</span> : null}
      </div>

      <section className={styles.section} aria-labelledby="net-about">
        <h3 id="net-about" className={styles.eyebrow}>
          About this service
        </h3>
        <p className={styles.muted}>{`Shared by ${entry.organisationName}`}</p>
        <dl className={styles.pairs}>
          <dt>Service</dt>
          <dd>{where}</dd>
          <dt>Source</dt>
          <dd>{entry.source === 'manual' ? 'Entered by the organisation' : 'From the Directory of Services'}</dd>
        </dl>
        {entry.presentation === 'unavailable' ? <p>Not available on the network. Phone to confirm.</p> : null}
      </section>

      <section className={styles.section} aria-labelledby="net-hours">
        <h3 id="net-hours" className={styles.eyebrow}>
          Opening hours
        </h3>
        <p>{hoursText(entry.openingHours)}</p>
      </section>

      <section className={styles.section} aria-labelledby="net-line">
        <h3 id="net-line" className={styles.eyebrow}>
          Service line
        </h3>
        {entry.contactPhone === null ? (
          <p>No number shared</p>
        ) : (
          <>
            <p>{`${entry.contactLabel ?? 'Service line'} ${entry.contactPhone}`}</p>
            <p>
              <a className={styles.phone} href={`tel:${entry.contactPhone.replace(/[^0-9+]/g, '')}`} data-el="NET-BOARD-PHONE-LINK">{`Phone ${entry.serviceName} on ${entry.contactPhone}`}</a>
            </p>
          </>
        )}
      </section>

      <section className={styles.section} aria-labelledby="net-criteria" data-el="NET-SERVICE-CRITERIA-SECTION">
        <h3 id="net-criteria" className={styles.eyebrow}>
          Criteria
        </h3>
        <p className={styles.muted}>Current criteria, read only</p>
        {load.kind === 'loading' ? (
          <Loading label="Loading the criteria">
            <SkeletonRows count={2} />
          </Loading>
        ) : load.criteria === 'unreadable' ? (
          <p>The criteria could not be read. Phone to confirm.</p>
        ) : load.criteria === null ? (
          <p>No criteria shared</p>
        ) : (
          <dl className={styles.pairs}>
            <dt>Accepts</dt>
            <dd>{needs(load.criteria.accepts)}</dd>
            <dt>Does not accept</dt>
            <dd>{needs(load.criteria.excludes)}</dd>
            <dt>Ages</dt>
            <dd>{agesText(load.criteria.ageMin, load.criteria.ageMax)}</dd>
            <dt>Districts</dt>
            <dd>{load.criteria.districts.length === 0 ? 'none listed' : load.criteria.districts.join(', ')}</dd>
            <dt>Review by</dt>
            <dd>{dayText(`${load.criteria.reviewBy}T12:00:00Z`)}</dd>
          </dl>
        )}
      </section>

      <p className={styles.note}>Shared by each organisation. No change reason, owner or history is shown here. Phone the service to check.</p>
    </div>
  );
}

function Directory({ networkId, networkName, ownOrganisation, ownHref, selectedRef }: { networkId: string; networkName: string; ownOrganisation: string | null; ownHref: string; selectedRef: string | undefined }) {
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
  const open = selectedRef === undefined ? undefined : entries.find((entry) => entry.rowRef === selectedRef);

  return (
    <main className={styles.page}>
      <h1 className={styles.title}>{`${networkName} services`}</h1>
      <ScopeHeader scope="network" networkName={networkName} switchTo={{ ownHref, networkHref: NETWORK_ROUTES.services }} />
      <ReadOnlyNote />
      {load.kind === 'loading' ? (
        <Loading label="Loading the services">
          <SkeletonRows count={3} />
        </Loading>
      ) : null}
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
            <Chip pressed={category === null} onPressedChange={() => setCategory(null)} dataEl="NET-SERVICES-CATEGORY-CHIP">
              Any category
            </Chip>
            {categories.map((code) => (
              <Chip key={code} pressed={category === code} onPressedChange={(next) => setCategory(next ? code : null)} dataEl="NET-SERVICES-CATEGORY-CHIP">
                {categoryLabel(code)}
              </Chip>
            ))}
          </div>
          <StageGrid stage={selectedRef === undefined ? 0 : 1} templates={STAGE_TEMPLATES} gaps={STAGE_GAPS} className={styles.stage}>
            <StageArea name="list">
              {visible.length === 0 ? (
                <div role="status">
                  <p>No services match this filter</p>
                  <p>Clear the filter to see all organisations.</p>
                </div>
              ) : (
                <ul className={styles.list} aria-label="Services">
                  {visible.map((entry) => (
                    <NetworkServiceCard key={entry.rowRef} entry={entry} own={ownRow(entry.organisationName, ownOrganisation)} orgRef={refOf.get(entry.organisationName) ?? 'org-0'} selected={entry.rowRef === selectedRef} />
                  ))}
                </ul>
              )}
            </StageArea>
            <StageArea name="stage">
              {selectedRef === undefined || load.kind !== 'ready' ? null : (
                <StageLayer index={1} current={1}>
                  {open === undefined ? (
                    <div className={styles.card} role="status">
                      <p className={styles.name}>Network view not available</p>
                      <p className={styles.muted}>Ask your administrator.</p>
                    </div>
                  ) : (
                    <ServicePane key={open.rowRef} networkId={networkId} entry={open} ownOrganisation={ownOrganisation} />
                  )}
                </StageLayer>
              )}
            </StageArea>
          </StageGrid>
        </>
      ) : null}
    </main>
  );
}

/** The directory, with a service open beside it when `selectedRef` names one (the board NServices). */
export function NetworkServicesView({ ownHref, selectedRef }: { ownHref: string; selectedRef?: string }) {
  return (
    <NetworkScope ownHref={ownHref} networkHref={NETWORK_ROUTES.services}>
      {({ network, ownOrganisation }) => <Directory networkId={network.id} networkName={network.name} ownOrganisation={ownOrganisation} ownHref={ownHref} selectedRef={selectedRef} />}
    </NetworkScope>
  );
}
