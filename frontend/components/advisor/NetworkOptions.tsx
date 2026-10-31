'use client';

import { useState } from 'react';
import { NetworkScope } from '@/components/network/NetworkScope';
import { NetworkUnavailable } from '@/components/scope/NetworkUnavailable';
import { ReadOnlyNote } from '@/components/scope/ReadOnlyNote';
import { ScopeHeader } from '@/components/scope/ScopeHeader';
import type { ScopeLinks } from '@/components/scope/ScopeSwitch';
import { Button } from '@/components/ui/Button';
import type { OptionsParts } from '@/lib/advisor/options';
import { useNetworkOptions } from '@/lib/network/useNetworkOptions';
import { NetworkCriteriaDialog } from './NetworkCriteriaDialog';
import { NotSuitableList } from './NotSuitableList';
import { ServiceCard } from './ServiceCard';
import { ViewToggle } from './ViewToggle';
import styles from './OptionsList.module.css';

// The options of a case in the network (docs/design/network-ui.md section 9, "Options and not-suitable list",
// WB11): the services of the OTHER organisations in the network that meet the case's criteria, read only,
// labelled by organisation, in the order the back end sent them (travel time, then organisation and service:
// "Sorted by travel time. Not ranked."). A row has no Request booking, no I phoned, no They declined and no
// clinical escalation: the only thing to do with a row is to phone the service on its service line, and the
// advisor records the call in their own case (DEC-134 item 8). The case screens are the organisation's own
// and are not changed here. The case's postcode, age and needs never leave the organisation: this page
// sends the network's id and the case's reference, and nothing else of the case.

function headingFor(count: number, network: string): string {
  return count === 1 ? `1 service in ${network} meets this patient’s criteria` : `${count} services in ${network} meet this patient’s criteria`;
}

type Open = { rowRef: string; serviceName: string; organisation: string };

function Body({ caseId, networkId, networkName, switchTo }: { caseId: string; networkId: string; networkName: string; switchTo: ScopeLinks }) {
  const { state, retry } = useNetworkOptions(networkId, caseId);
  const [open, setOpen] = useState<Open | null>(null);

  if (state.kind === 'loading') return <p>Loading the options.</p>;
  if (state.kind === 'refused') return <NetworkUnavailable reason="not-available" ownHref={switchTo.ownHref} />;
  if (state.kind === 'failed') {
    return (
      <div>
        <ScopeHeader scope="network" networkName={networkName} switchTo={switchTo} />
        <p role="alert">The network options could not be read. Phone services to check.</p>
        <Button variant="secondary" onClick={retry} dataEl="NET-STATE-RETRY-BTN">
          Try again
        </Button>
      </div>
    );
  }
  return <Ready parts={state.parts} caseId={caseId} networkId={networkId} networkName={networkName} switchTo={switchTo} open={open} setOpen={setOpen} />;
}

function Ready({
  parts,
  caseId,
  networkId,
  networkName,
  switchTo,
  open,
  setOpen,
}: {
  parts: OptionsParts;
  caseId: string;
  networkId: string;
  networkName: string;
  switchTo: ScopeLinks;
  open: Open | null;
  setOpen: (open: Open | null) => void;
}) {
  const { options, notSuitable } = parts;
  const link = (path: string) => `/advisor/case/${encodeURIComponent(caseId)}/${path}`;
  const criteriaFor = (rowRef: string) => {
    const option = options.find((candidate) => candidate.serviceId === rowRef);
    if (option !== undefined) setOpen({ rowRef, serviceName: option.name, organisation: option.network?.organisation ?? '' });
  };

  return (
    <section className={styles.list} aria-label="Options in the network">
      <ScopeHeader scope="network" networkName={networkName} switchTo={switchTo} />
      <ViewToggle caseId={caseId} current="list" scope="network" />
      <ReadOnlyNote />
      {options.length === 0 ? (
        <p role="status">
          {parts.notFound
            ? 'We could not place this postcode, so no travel time can be shown.'
            : parts.outOfArea
              ? `No service in ${networkName} covers this postcode.`
              : `No service in ${networkName} meets this patient’s criteria. Phone services to check.`}
        </p>
      ) : (
        <>
          <h2 className={styles.heading}>{headingFor(options.length, networkName)}</h2>
          <p className={styles.sub}>Sorted by travel time. Not ranked.</p>
          <div className={styles.cards}>
            {options.map((option) => (
              <ServiceCard key={option.serviceId} caseId={caseId} option={option} onCriteria={criteriaFor} />
            ))}
          </div>
        </>
      )}

      {open === null ? null : (
        <NetworkCriteriaDialog networkId={networkId} rowRef={open.rowRef} serviceName={open.serviceName} organisationName={open.organisation} onClose={() => setOpen(null)} />
      )}

      <NotSuitableList items={notSuitable} />

      <footer className={styles.footer}>
        <p className={styles.note}>No patient name is stored. Postcode and needs are cleared after the call record closes.</p>
        <div className={styles.actions}>
          <Button variant="neutral" href={link('finish')}>
            Record outcome
          </Button>
          <Button variant="neutral" href={switchTo.ownHref}>
            Back to our organisation’s options
          </Button>
        </div>
      </footer>
    </section>
  );
}

export function NetworkOptions({ caseId }: { caseId: string }) {
  const base = `/advisor/case/${encodeURIComponent(caseId)}`;
  return (
    <NetworkScope ownHref={`${base}/options`} networkHref={`${base}/network-options`}>
      {({ network, switchTo }) => <Body caseId={caseId} networkId={network.id} networkName={network.name} switchTo={switchTo} />}
    </NetworkScope>
  );
}
