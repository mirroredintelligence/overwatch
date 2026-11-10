'use client';

import { useState } from 'react';
import { NetworkScope } from '@/components/network/NetworkScope';
import { NetworkUnavailable } from '@/components/scope/NetworkUnavailable';
import { ReadOnlyNote } from '@/components/scope/ReadOnlyNote';
import { ScopeHeader } from '@/components/scope/ScopeHeader';
import type { ScopeLinks } from '@/components/scope/ScopeSwitch';
import { Button } from '@/components/ui/Button';
import { useNetworkOptions } from '@/lib/network/useNetworkOptions';
import { NetworkCriteriaDialog } from './NetworkCriteriaDialog';
import { MapLoadingBox } from '@/components/map/MapLoadingBox';
import { useMapPreload } from '@/components/map/TileMap';
import { OptionsMap } from './OptionsMap';
import { ViewToggle } from './ViewToggle';
import styles from './map.module.css';

// The map of the network's options (docs/design/network-ui.md section 9, "Map", WB11): the same services as
// the network list, each with a place drawn as a pin, the same two toggles as the advisor's own map, and no
// booking action. A service that shared no place has no pin and the page says so: the list holds every
// service. Nothing here is a tile provider or a third-party script, as the own map. The case's postcode
// never leaves the organisation: the page sends the network's id and the case's reference only.

type Open = { rowRef: string; serviceName: string; organisation: string };

function Body({ caseId, networkId, networkName, switchTo }: { caseId: string; networkId: string; networkName: string; switchTo: ScopeLinks }) {
  useMapPreload();
  const { state, retry } = useNetworkOptions(networkId, caseId);
  const [selected, setSelected] = useState<string | null>(null);
  const [open, setOpen] = useState<Open | null>(null);

  if (state.kind === 'loading') return <MapLoadingBox />;
  if (state.kind === 'refused') return <NetworkUnavailable reason="not-available" ownHref={switchTo.ownHref} />;
  if (state.kind === 'failed') {
    return (
      <div>
        <ScopeHeader scope="network" networkName={networkName} switchTo={switchTo} />
        <p role="alert">The network map could not be read. Phone services to check.</p>
        <Button variant="secondary" onClick={retry} dataEl="NET-STATE-RETRY-BTN">
          Try again
        </Button>
      </div>
    );
  }

  const { parts } = state;
  const header = <ScopeHeader scope="network" networkName={networkName} switchTo={switchTo} />;
  if (parts.notFound) {
    return (
      <section className={styles.screen} aria-label="Map">
        {header}
        <ViewToggle caseId={caseId} current="map" scope="network" />
        <p role="status">We could not place this postcode, so the map cannot be drawn.</p>
      </section>
    );
  }
  if (parts.outOfArea) {
    return (
      <section className={styles.screen} aria-label="Map">
        {header}
        <ViewToggle caseId={caseId} current="map" scope="network" />
        <p role="status">{`No service in ${networkName} covers this postcode.`}</p>
      </section>
    );
  }

  const unplaced = parts.options.filter((option) => option.position === null && option.coverage === null).length;
  const openCriteria = (rowRef: string) => {
    const option = parts.options.find((candidate) => candidate.serviceId === rowRef);
    if (option !== undefined) setOpen({ rowRef, serviceName: option.name, organisation: option.network?.organisation ?? '' });
  };
  return (
    <section className={styles.screen} aria-label="Map">
      {header}
      <ViewToggle caseId={caseId} current="map" scope="network" />
      <h2 className={styles.heading}>{`Options in ${networkName} near this patient`}</h2>
      <p className={styles.sub}>Same services as the list. Sorted by travel time. Not ranked.</p>
      <ReadOnlyNote />
      <OptionsMap
        caseId={caseId}
        postcode="this patient"
        patientArea={parts.patientArea}
        options={parts.options}
        selectedId={selected}
        onSelect={setSelected}
        onNetworkCriteria={openCriteria}
      />
      {unplaced === 0 ? null : <p className={styles.sub}>{`${unplaced} ${unplaced === 1 ? 'service has' : 'services have'} no place on the map. See the list.`}</p>}
      {open === null ? null : (
        <NetworkCriteriaDialog networkId={networkId} rowRef={open.rowRef} serviceName={open.serviceName} organisationName={open.organisation} onClose={() => setOpen(null)} />
      )}
    </section>
  );
}

export function NetworkMap({ caseId }: { caseId: string }) {
  const base = `/advisor/case/${encodeURIComponent(caseId)}`;
  return (
    <NetworkScope ownHref={`${base}/map`} networkHref={`${base}/network-map`}>
      {({ network, switchTo }) => <Body caseId={caseId} networkId={network.id} networkName={network.name} switchTo={switchTo} />}
    </NetworkScope>
  );
}
