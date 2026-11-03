'use client';

import { useState } from 'react';
import { Chip } from '@/components/ui/Chip';
import { Loading, SkeletonRows } from '@/components/ui/Skeleton';
import { BASE, useAdminRead, type GrantsRead, type ListingsRead, type OverviewRead } from '@/lib/networkAdmin/browser';
import type { GrantRow, ListingRow, MemberRow } from '@/lib/networkAdmin/views';
import { dateText, reasonWord, SCOPE_WORD } from '@/lib/networkAdmin/words';
import styles from './NetworkAdminHistory.module.css';
import { OwnedNetworkGate } from './OwnedNetworkGate';

// The read-only history of the network's membership, grant and listing decisions, with their dates (TEN-080, design
// NAdminHistory). Nothing here can be changed, and nothing of what an organisation shared: only who joined and left,
// which grants were approved, ended, lapsed, replaced or declined, and which listings were decided, and when.
// The reads carry no role for who made a decision, so the list does not name one (see the report).

export function NetworkAdminHistory() {
  return (
    <main className={styles.page}>
      <h1 className={styles.title}>History</h1>
      <p className={styles.text}>Read-only history of membership and grant decisions, with their dates. It names roles, never people.</p>
      <OwnedNetworkGate>{(query) => <History query={query} />}</OwnedNetworkGate>
    </main>
  );
}

type Kind = 'all' | 'membership' | 'grants' | 'listings';
const KINDS: readonly (readonly [Kind, string])[] = [
  ['all', 'All'],
  ['membership', 'Membership'],
  ['grants', 'Grants'],
  ['listings', 'Listings'],
];

/** One decision on the list: its date (an ISO time, or null when none was recorded), what it was and about whom. */
type Decision = {
  kind: Exclude<Kind, 'all'>;
  at: string | null;
  title: string;
  detail: string;
  /** A decision that closed something (a membership or a grant ended, a listing declined or withdrawn): a hollow mark. */
  closed: boolean;
};

function membershipDecisions(members: readonly MemberRow[]): Decision[] {
  return members.flatMap((member): Decision[] => {
    const out: Decision[] = [];
    if (member.joinedAt !== null) {
      const accepted = member.acceptedAgreementVersion === null ? 'joined the network' : `accepted agreement version ${member.acceptedAgreementVersion}`;
      out.push({ kind: 'membership', at: member.joinedAt, title: 'Membership started', detail: `${member.organisation} ${accepted}`, closed: false });
    }
    if (member.status === 'left' || member.status === 'removed') {
      const ended = member.status === 'left' ? 'left the network' : 'was removed from the network';
      out.push({ kind: 'membership', at: member.leftAt, title: 'Membership ended', detail: `${member.organisation} ${ended}`, closed: true });
    }
    return out;
  });
}

function grantDecisions(grants: readonly GrantRow[]): Decision[] {
  return grants.flatMap((grant): Decision[] => {
    const scope = `${grant.organisation} · ${SCOPE_WORD[grant.scope]}`;
    const out: Decision[] = [];
    if (grant.grantorApprovedAt !== null && grant.ownerApprovedAt !== null) {
      // The grant came into force when its second approval was given: the later of the two.
      const first = grant.grantorApprovedAt;
      const second = grant.ownerApprovedAt;
      const at = Date.parse(first) >= Date.parse(second) ? first : second;
      out.push({ kind: 'grants', at, title: 'Grant approved', detail: scope, closed: false });
    }
    switch (grant.status) {
      case 'ended':
        out.push({ kind: 'grants', at: grant.endedAt, title: 'Grant ended', detail: scope, closed: true });
        break;
      case 'lapsed':
        out.push({ kind: 'grants', at: grant.endedAt, title: 'Grant lapsed', detail: scope, closed: true });
        break;
      case 'superseded':
        out.push({ kind: 'grants', at: grant.endedAt, title: 'Grant replaced', detail: scope, closed: true });
        break;
      case 'declined':
        out.push({ kind: 'grants', at: null, title: 'Grant declined', detail: scope, closed: true });
        break;
      default:
        break;
    }
    return out;
  });
}

const LISTING_TITLE: Readonly<Partial<Record<ListingRow['status'], [string, boolean]>>> = {
  admitted: ['Listing admitted', false],
  suspended: ['Listing paused', false],
  declined: ['Listing declined', true],
  withdrawn: ['Listing withdrawn', true],
};

function listingDecisions(listings: readonly ListingRow[]): Decision[] {
  return listings.flatMap((listing): Decision[] => {
    const shape = LISTING_TITLE[listing.status];
    if (shape === undefined || listing.decidedAt === null) return [];
    const reason = listing.reason === null ? null : `reason: ${reasonWord(listing.reason)}`;
    const detail = [listing.organisation, reason].filter((part) => part !== null).join(' · ');
    return [{ kind: 'listings', at: listing.decidedAt, title: shape[0], detail, closed: shape[1] }];
  });
}

/** Newest first; a decision with no date goes last. The sort is stable, so equal dates keep their order. */
function newestFirst(a: Decision, b: Decision): number {
  if (a.at === null || b.at === null) return a.at === null ? (b.at === null ? 0 : 1) : -1;
  return Date.parse(b.at) - Date.parse(a.at);
}

function History({ query }: { query: string }) {
  const members = useAdminRead<OverviewRead>(`${BASE}${query}`);
  const grants = useAdminRead<GrantsRead>(`${BASE}/grants${query}`);
  const listings = useAdminRead<ListingsRead>(`${BASE}/listings${query}`);
  const [kind, setKind] = useState<Kind>('all');

  if (members.state.status === 'loading' || grants.state.status === 'loading' || listings.state.status === 'loading') {
    return (
      <Loading label="Loading the history.">
        <SkeletonRows count={3} />
      </Loading>
    );
  }
  if (members.state.status === 'failed' || grants.state.status === 'failed' || listings.state.status === 'failed') {
    return (
      <p role="alert" className={styles.problem}>
        We could not load the history.
      </p>
    );
  }
  const decisions = [
    ...membershipDecisions(members.state.data.network.members),
    ...grantDecisions(grants.state.data.grants),
    ...listingDecisions(listings.state.data.listings),
  ].sort(newestFirst);
  const shown = kind === 'all' ? decisions : decisions.filter((decision) => decision.kind === kind);
  return (
    <>
      <div role="group" aria-label="Which decisions" className={styles.chips}>
        {KINDS.map(([id, label]) => (
          <Chip key={id} pressed={kind === id} onPressedChange={() => setKind(id)}>
            {label}
          </Chip>
        ))}
      </div>
      <section className={styles.card}>
        {shown.length === 0 ? (
          <p className={styles.empty}>
            Nothing here yet.
            <span className={styles.muted}>{' A decision that is made stays here, with its date.'}</span>
          </p>
        ) : (
          <ol className={styles.list} aria-label="Decisions">
            {shown.map((decision, index) => (
              <li key={`${decision.kind}-${index}`} className={styles.item}>
                <time className={styles.date} dateTime={decision.at ?? undefined}>
                  {decision.at === null ? 'No date recorded' : dateText(decision.at)}
                </time>
                <span aria-hidden="true" className={decision.closed ? `${styles.dot} ${styles.closed}` : styles.dot} />
                <div className={styles.what}>
                  <b>{decision.title}</b>
                  <small>{decision.detail}</small>
                </div>
              </li>
            ))}
          </ol>
        )}
      </section>
      <p className={styles.note}>Decisions are never edited or removed.</p>
    </>
  );
}
