import { categoryLabel } from '@/lib/board/format';
import { hoursText } from '@/lib/network/hours';
import type { NetworkDirectoryEntry } from '@/lib/network/types';
import { OrgLabel } from './OrgLabel';
import styles from '@/components/network/Network.module.css';

// One service of the network directory (docs/design/network-ui.md, NetworkServices, TEN-071): its name is
// the one link, to the detail by the opaque row reference. It says whose service it is, what it is and
// where, when it is open and how to phone it. A paused listing says it is not available on the network.

export function NetworkServiceCard({ entry, own, orgRef }: { entry: NetworkDirectoryEntry; own: boolean; orgRef: string }) {
  const kind = [categoryLabel(entry.category), entry.location?.postalDistrict ?? null].filter((part): part is string => part !== null).join(' · ');
  const paused = entry.presentation === 'unavailable';
  return (
    <li className={styles.row} data-el="NET-SERVICES-ROW" data-service-ref={entry.rowRef} data-org-ref={orgRef}>
      <h2 className={styles.rowTitle}>
        <a href={`/network/services/${encodeURIComponent(entry.rowRef)}`}>{entry.serviceName}</a>
      </h2>
      <OrgLabel name={entry.organisationName} own={own} />
      <p className={styles.muted}>{kind}</p>
      {paused ? <p className={styles.muted}>Not available on the network. Phone to confirm.</p> : null}
      <p className={styles.muted}>{hoursText(entry.openingHours)}</p>
      <p className={styles.muted}>{entry.contactPhone === null ? 'No number shared' : `${entry.contactLabel ?? 'Service line'} ${entry.contactPhone}`}</p>
    </li>
  );
}
