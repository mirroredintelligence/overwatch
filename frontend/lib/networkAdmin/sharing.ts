import { dateText, waitsForOrganisation } from './words';
import type { GrantRow, KindState, Scope } from './views';

// What a member's administrator sees of one kind of sharing, worked out from the organisation's own grants
// for the network and what the network holds of it (TEN-081, design N2: SharingOverview). Pure: no import of
// the server, no clock. The states are the design's five (`Sharing since`, `Waiting for your approval`,
// `Waiting for the network owner`, `Not sharing`, `Ended on`), and one more, said in words: an approved grant
// whose window has not started yet is not sharing yet, and saying "Sharing since" for it would be untrue.

export type CardState =
  | { kind: 'sharing'; since: string }
  | { kind: 'scheduled'; from: string }
  | { kind: 'waiting-you' }
  | { kind: 'waiting-owner' }
  | { kind: 'not-sharing' }
  | { kind: 'ended'; on: string };

export type Arrival = { kind: 'receiving' } | { kind: 'stopped'; at: string } | { kind: 'none' };

export type Card = {
  scope: Scope;
  state: CardState;
  /** The grant the organisation's administrator may approve or decline now, or null. */
  waitingFor: string | null;
  /** The grant in force or about to be that the organisation may end, or null. */
  endable: string | null;
  /** When the grant in force started, said while a newer version waits for approval. */
  inForceSince: string | null;
  arrival: Arrival;
};

const CLOSED = new Set(['ended', 'lapsed', 'superseded', 'declined']);

const newest = (grants: GrantRow[]): GrantRow | undefined => [...grants].sort((a, b) => b.version - a.version)[0];
const latestEnding = (grants: GrantRow[]): GrantRow | undefined =>
  [...grants].sort((a, b) => (b.endedAt ?? b.effectiveFrom).localeCompare(a.endedAt ?? a.effectiveFrom) || b.version - a.version)[0];

export function cardFor(scope: Scope, grants: GrantRow[], shared: KindState[]): Card {
  const mine = grants.filter((grant) => grant.scope === scope);
  const waitingYou = newest(mine.filter(waitsForOrganisation));
  const waitingOwner = newest(mine.filter((grant) => grant.status === 'grantor-approved'));
  const approved = newest(mine.filter((grant) => grant.status === 'approved'));
  const closed = latestEnding(mine.filter((grant) => CLOSED.has(grant.status)));
  const inForce = approved !== undefined && approved.effective ? approved : undefined;

  let state: CardState;
  if (waitingYou !== undefined) state = { kind: 'waiting-you' };
  else if (waitingOwner !== undefined) state = { kind: 'waiting-owner' };
  else if (approved !== undefined) state = inForce !== undefined ? { kind: 'sharing', since: approved.effectiveFrom } : { kind: 'scheduled', from: approved.effectiveFrom };
  else if (closed !== undefined && closed.status !== 'declined' && closed.endedAt !== null) state = { kind: 'ended', on: closed.endedAt };
  else state = { kind: 'not-sharing' };

  const source = shared.find((kind) => kind.kind === scope);
  let arrival: Arrival = { kind: 'none' };
  if (source?.status === 'active') arrival = { kind: 'receiving' };
  else if (source?.status === 'ended' && source.endedAt !== null) arrival = { kind: 'stopped', at: source.endedAt };

  return {
    scope,
    state,
    waitingFor: waitingYou?.id ?? null,
    endable: state.kind === 'sharing' || state.kind === 'scheduled' ? (approved?.id ?? null) : null,
    inForceSince: waitingYou !== undefined || waitingOwner !== undefined ? (inForce?.effectiveFrom ?? null) : null,
    arrival,
  };
}

/** The state in the design's words. */
export function cardWord(state: CardState): string {
  switch (state.kind) {
    case 'sharing':
      return `Sharing since ${dateText(state.since)}`;
    case 'scheduled':
      return `Approved. Sharing starts on ${dateText(state.from)}`;
    case 'waiting-you':
      return 'Waiting for your approval';
    case 'waiting-owner':
      return 'Waiting for the network owner';
    case 'not-sharing':
      return 'Not sharing';
    case 'ended':
      return `Ended on ${dateText(state.on)}`;
  }
}

/** Whether the network is getting this kind, said only when there is something to say. */
export function arrivalWord(card: Pick<Card, 'state' | 'arrival'>): string | null {
  if (card.arrival.kind === 'receiving') return 'The network is receiving this.';
  if (card.arrival.kind === 'stopped') return `The network stopped receiving this on ${dateText(card.arrival.at)}.`;
  return card.state.kind === 'sharing' ? 'Nothing has arrived on the network yet.' : null;
}
