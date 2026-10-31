'use client';

import { Card } from '@/components/ui/Card';
import { BASE, useAdminRead, type GrantsRead, type OverviewRead } from '@/lib/networkAdmin/browser';
import { dateText, SCOPE_WORD } from '@/lib/networkAdmin/words';
import type { GrantRow, MemberRow } from '@/lib/networkAdmin/views';
import styles from '../admin/admin.module.css';
import { OwnedNetworkGate } from './OwnedNetworkGate';

// The read-only history of the network's membership and grant decisions, with their dates (TEN-080, design
// N1: NetworkAdminHistory). Nothing here can be changed, and nothing of what an organisation shared: only who
// joined and left, and which grants ended, lapsed or were declined, and when.

export function NetworkAdminHistory() {
  return (
    <main className={styles.page}>
      <h1 className={styles.title}>History</h1>
      <p className={styles.text}>Read-only history of membership and grant decisions, with their dates.</p>
      <OwnedNetworkGate>{(query) => <History query={query} />}</OwnedNetworkGate>
    </main>
  );
}

const CLOSED_GRANT: ReadonlySet<string> = new Set(['ended', 'lapsed', 'declined', 'superseded']);

function memberText(member: MemberRow): string {
  return member.status === 'left' ? `Left the network on ${dateText(member.leftAt)}` : `Removed from the network on ${dateText(member.leftAt)}`;
}

function grantText(grant: GrantRow): string {
  switch (grant.status) {
    case 'ended':
      return `Ended on ${dateText(grant.endedAt)}`;
    case 'lapsed':
      return `Lapsed on ${dateText(grant.endedAt)}`;
    case 'superseded':
      return `Replaced on ${dateText(grant.endedAt)}`;
    default:
      return 'Declined';
  }
}

function History({ query }: { query: string }) {
  const members = useAdminRead<OverviewRead>(`${BASE}${query}`);
  const grants = useAdminRead<GrantsRead>(`${BASE}/grants${query}`);
  if (members.state.status === 'loading' || grants.state.status === 'loading') return <p className={styles.muted}>Loading the history.</p>;
  if (members.state.status === 'failed' || grants.state.status === 'failed') {
    return (
      <p role="alert" className={styles.problem}>
        We could not load the history.
      </p>
    );
  }
  const closedMembers = members.state.data.network.members.filter((m) => m.status === 'left' || m.status === 'removed');
  const closedGrants = grants.state.data.grants.filter((g) => CLOSED_GRANT.has(g.status));
  return (
    <>
      <Card heading="Members">
        <div className={styles.scroll}>
          <table className={styles.table}>
            <caption>Membership history</caption>
            <thead>
              <tr>
                <th scope="col">Organisation</th>
                <th scope="col">What happened</th>
              </tr>
            </thead>
            <tbody>
              {closedMembers.length === 0 ? (
                <tr>
                  <td colSpan={2}>Nothing here yet.</td>
                </tr>
              ) : (
                closedMembers.map((member) => (
                  <tr key={member.id} data-row-ref={member.id}>
                    <td>{member.organisation}</td>
                    <td>{memberText(member)}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </Card>
      <Card heading="Grants">
        <div className={styles.scroll}>
          <table className={styles.table}>
            <caption>Grant history</caption>
            <thead>
              <tr>
                <th scope="col">Organisation</th>
                <th scope="col">Scope</th>
                <th scope="col">What happened</th>
              </tr>
            </thead>
            <tbody>
              {closedGrants.length === 0 ? (
                <tr>
                  <td colSpan={3}>Nothing here yet.</td>
                </tr>
              ) : (
                closedGrants.map((grant) => (
                  <tr key={grant.id} data-row-ref={grant.id}>
                    <td>{grant.organisation}</td>
                    <td>{SCOPE_WORD[grant.scope]}</td>
                    <td>{grantText(grant)}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </Card>
    </>
  );
}
