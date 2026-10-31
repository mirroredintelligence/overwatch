'use client';

import { useState, type ReactNode } from 'react';
import { Chip } from '@/components/ui/Chip';
import { BASE, queryFor, useAdminRead, type NetworksRead } from '@/lib/networkAdmin/browser';
import styles from '../admin/admin.module.css';

// The gate of every network administration page (TEN-080): which network is this person running? The server
// answers from the registry. None: the one refusal wording of the network screens (design section 5), and
// nothing else is read. One: the page reads without naming it. Several: the page asks which and reads nothing
// of a network until one is chosen; the id is one the server offered and never an authority.

export function OwnedNetworkGate({ children }: { children: (query: string) => ReactNode }) {
  const { state } = useAdminRead<NetworksRead>(`${BASE}/networks`);
  const [chosen, setChosen] = useState<string | null>(null);

  if (state.status === 'loading') return <p className={styles.muted}>Loading the network.</p>;
  if (state.status === 'failed') {
    return (
      <p role="alert" className={styles.problem}>
        We could not load the network.
      </p>
    );
  }
  const { networks } = state.data;
  if (networks.length === 0) {
    return (
      <div className={styles.panel} role="status" data-el="NET-STATE-PANEL">
        <h2 className={styles.title}>Network view not available</h2>
        <p className={styles.text}>Ask your administrator.</p>
      </div>
    );
  }
  if (networks.length === 1) return <>{children('')}</>;
  return (
    <>
      <section aria-label="Which network" className={styles.stack}>
        <p className={styles.text}>Which network?</p>
        <div className={styles.row}>
          {networks.map((network) => (
            <Chip key={network.id} pressed={chosen === network.id} onPressedChange={() => setChosen(network.id)}>
              {network.name}
            </Chip>
          ))}
        </div>
      </section>
      {chosen === null ? null : <div key={chosen}>{children(queryFor(chosen))}</div>}
    </>
  );
}
