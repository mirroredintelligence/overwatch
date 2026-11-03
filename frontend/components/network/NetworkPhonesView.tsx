'use client';

import { useEffect, useState } from 'react';
import { DataTable, type DataTableColumn } from '@/components/data/DataTable';
import { NetworkUnavailable } from '@/components/scope/NetworkUnavailable';
import { PhoneLink } from '@/components/scope/PhoneLink';
import { ScopeHeader } from '@/components/scope/ScopeHeader';
import { Chip } from '@/components/ui/Chip';
import { readNetworkView } from '@/lib/network/browser';
import { NETWORK_ROUTES } from '@/lib/network/links';
import { ownRow } from '@/lib/network/orgs';
import { parsePhones } from '@/lib/network/parse';
import type { NetworkPhone, NetworkPhones } from '@/lib/network/types';
import { NetworkScope } from './NetworkScope';
import styles from './Network.module.css';
import own from './NetworkPhonesView.module.css';

// "Phones and services" of the network (W43, network variant, `GET /network/{id}/phones`): each service of
// the network and the service line its organisation shared. Phoning is the only action. A reporter's
// number, a cover, a role and a move are an organisation's own and are never shared, so none is here
// (DEC-136 items 1 and 5). A service with no line says "Phone to confirm".

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const londonParts = new Intl.DateTimeFormat('en-GB', { timeZone: 'Europe/London', day: 'numeric', month: 'numeric', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' });

/** "23 Oct 14:08" in London time. */
function reportedText(instant: string): string {
  const parts = londonParts.formatToParts(Date.parse(instant));
  const part = (type: string) => parts.find((p) => p.type === type)?.value ?? '';
  return `${part('day')} ${MONTHS[Number(part('month')) - 1] ?? ''} ${part('hour')}:${part('minute')}`;
}

const countWord = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

/** The last report: a paused listing has none to show, a late one says so beside its time. */
function reportedCell(phone: NetworkPhone): string {
  if (phone.presentation === 'unavailable' || phone.status === null) return 'Not available on the network';
  if (phone.reportedAt === null) return 'No figure reported yet';
  return phone.staleWarning ? `${reportedText(phone.reportedAt)}, not updated since` : reportedText(phone.reportedAt);
}

type Load = { kind: 'loading' } | { kind: 'ready'; phones: NetworkPhones } | { kind: 'refused' } | { kind: 'failed' };

function Phones({ networkId, networkName, ownOrganisation, ownHref }: { networkId: string; networkName: string; ownOrganisation: string | null; ownHref: string }) {
  const [load, setLoad] = useState<Load>({ kind: 'loading' });
  // The organisation the chips filter to; null is every organisation.
  const [chosen, setChosen] = useState<string | null>(null);

  useEffect(() => {
    let current = true;
    void readNetworkView('phones', networkId, (body) => parsePhones(body, 'bff')).then((result) => {
      if (!current) return;
      if (result.ok) setLoad({ kind: 'ready', phones: result.data });
      else if ([401, 403, 404].includes(result.status)) setLoad({ kind: 'refused' });
      else setLoad({ kind: 'failed' });
    });
    return () => {
      current = false;
    };
  }, [networkId]);

  if (load.kind === 'refused') return <main className={styles.page}><NetworkUnavailable reason="not-available" ownHref={ownHref} /></main>;

  const columns: readonly DataTableColumn<NetworkPhone>[] = [
    {
      key: 'service',
      header: 'Service',
      cell: (phone) => (
        <>
          <span className={own.service}>{phone.serviceName}</span>
          {ownRow(phone.organisationName, ownOrganisation) ? <span className={own.own} data-own="true">Your organisation</span> : null}
        </>
      ),
    },
    { key: 'organisation', header: 'Organisation', cell: (phone) => phone.organisationName },
    {
      key: 'line',
      header: 'Service line',
      cell: (phone) => (phone.contactPhone === null ? 'Phone to confirm' : <PhoneLink serviceName={phone.serviceName} phone={phone.contactPhone} />),
    },
    { key: 'reported', header: 'Last reported', cell: reportedCell },
  ];

  if (load.kind !== 'ready') {
    return (
      <main className={styles.page}>
        <h1 className={styles.title}>{`${networkName} phones`}</h1>
        <ScopeHeader scope="network" networkName={networkName} switchTo={{ ownHref, networkHref: NETWORK_ROUTES.phones }} />
        {load.kind === 'failed' ? <p role="alert">We could not load the phones.</p> : <p role="status">Loading the phones</p>}
      </main>
    );
  }

  const organisations = [...new Set(load.phones.phones.map((phone) => phone.organisationName))];
  // A choice that the network no longer has shows every organisation, never an empty table.
  const filter = chosen !== null && organisations.includes(chosen) ? chosen : null;
  const shown = filter === null ? load.phones.phones : load.phones.phones.filter((phone) => phone.organisationName === filter);
  const shownOrganisations = new Set(shown.map((phone) => phone.organisationName)).size;

  return (
    <main className={styles.page}>
      <h1 className={styles.title}>{`${networkName} phones`}</h1>
      <ScopeHeader scope="network" networkName={networkName} switchTo={{ ownHref, networkHref: NETWORK_ROUTES.phones }} />
      <div className={own.summary}>
        <p className={own.count}>{`${countWord(shown.length, 'service', 'services')} from ${countWord(shownOrganisations, 'organisation', 'organisations')}`}</p>
        <div className={styles.chips}>
          <Chip pressed={filter === null} onPressedChange={() => setChosen(null)}>
            All organisations
          </Chip>
          {organisations.map((name) => (
            <Chip key={name} pressed={filter === name} onPressedChange={(next) => setChosen(next ? name : null)}>
              {name}
            </Chip>
          ))}
        </div>
      </div>
      <div className={own.card}>
        <DataTable caption="Services in the network and their service lines" columns={columns} rows={shown} getRowKey={(phone) => phone.rowRef} />
      </div>
      <p className={own.note}>Phoning is the only action. Reporters’ phones, covers and moves are your organisation’s own and are not shared across the network. No patient information on this screen.</p>
    </main>
  );
}

export function NetworkPhonesView({ ownHref }: { ownHref: string }) {
  return (
    <NetworkScope ownHref={ownHref} networkHref={NETWORK_ROUTES.phones}>
      {({ network, ownOrganisation }) => <Phones networkId={network.id} networkName={network.name} ownOrganisation={ownOrganisation} ownHref={ownHref} />}
    </NetworkScope>
  );
}
