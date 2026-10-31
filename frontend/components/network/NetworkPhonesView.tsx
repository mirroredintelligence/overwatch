'use client';

import { useEffect, useState } from 'react';
import { NetworkUnavailable } from '@/components/scope/NetworkUnavailable';
import { OrgLabel } from '@/components/scope/OrgLabel';
import { ScopeHeader } from '@/components/scope/ScopeHeader';
import { StatusBadge } from '@/components/ui/StatusBadge';
import { categoryLabel } from '@/lib/board/format';
import { readNetworkView } from '@/lib/network/browser';
import { NETWORK_ROUTES } from '@/lib/network/links';
import { ownRow } from '@/lib/network/orgs';
import { parsePhones } from '@/lib/network/parse';
import type { NetworkPhones } from '@/lib/network/types';
import { NetworkScope } from './NetworkScope';
import styles from './Network.module.css';

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

type Load = { kind: 'loading' } | { kind: 'ready'; phones: NetworkPhones } | { kind: 'refused' } | { kind: 'failed' };

function Phones({ networkId, networkName, ownOrganisation, ownHref }: { networkId: string; networkName: string; ownOrganisation: string | null; ownHref: string }) {
  const [load, setLoad] = useState<Load>({ kind: 'loading' });

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

  return (
    <main className={styles.page}>
      <h1 className={styles.title}>{`${networkName} phones`}</h1>
      <ScopeHeader scope="network" networkName={networkName} switchTo={{ ownHref, networkHref: NETWORK_ROUTES.phones }} />
      {load.kind === 'failed' ? <p role="alert">We could not load the phones.</p> : null}
      {load.kind === 'loading' ? <p role="status">Loading the phones</p> : null}
      {load.kind === 'ready' ? (
        <>
          <p className={styles.muted}>{`${countWord(load.phones.phones.length, 'service', 'services')} from ${countWord(load.phones.organisations, 'organisation', 'organisations')}`}</p>
          <p className={styles.muted}>Reporters’ phones, covers and moves are your organisation’s own and are not shared across the network.</p>
          <table className={styles.table}>
            <caption>Services in the network and their service lines</caption>
            <thead>
              <tr>
                <th scope="col">Service</th>
                <th scope="col">Organisation</th>
                <th scope="col">Category</th>
                <th scope="col">Status</th>
                <th scope="col">Last report</th>
                <th scope="col">Service line</th>
              </tr>
            </thead>
            <tbody>
              {load.phones.phones.map((phone) => {
                const paused = phone.presentation === 'unavailable' || phone.status === null;
                return (
                  <tr key={phone.rowRef} data-service-ref={phone.rowRef}>
                    <th scope="row">{phone.serviceName}</th>
                    <td>
                      <OrgLabel name={phone.organisationName} own={ownRow(phone.organisationName, ownOrganisation)} />
                    </td>
                    <td>{categoryLabel(phone.category)}</td>
                    <td>{paused ? 'Not available on the network' : <StatusBadge status={phone.status ?? 'not-updated'} />}</td>
                    <td>{phone.reportedAt === null ? 'No figure reported yet' : reportedText(phone.reportedAt)}</td>
                    <td>
                      {phone.contactPhone === null ? (
                        'Phone to confirm'
                      ) : (
                        <a href={`tel:${phone.contactPhone.replace(/[^0-9+]/g, '')}`} aria-label={`Phone ${phone.serviceName} on ${phone.contactPhone}`}>
                          {phone.contactPhone}
                        </a>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </>
      ) : null}
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
