'use client';

import { useCallback, useState } from 'react';
import { bffRequest, type BffResult } from '@/lib/bff/browser';
import type { GrantRow, HealthRow, ListingRow, MemberRow } from './views';

// The network administration screens' calls to their BFF routes (TEN-080). A read says loading, ok or
// failed (`useAdminRead`); a write is one POST with the CSRF token (the shared browser client adds it). The
// back end has no idempotency key here: each command is repeatable by its state, so a retried submit is the
// same result. The network is chosen on the server; with more than one the page names one of the offered
// ids as the one key `networkId`, in the query of the BFF call only (never an address, a cookie or storage).

export { useAdminRead } from '@/lib/tenantAdmin/browser';

export const BASE = '/api/bff/network-admin';

export type NetworkChoice = { id: string; name: string };
export type NetworksRead = { networks: NetworkChoice[] };
export type OverviewRead = {
  network: {
    id: string;
    name: string;
    agreementReference: string | null;
    agreementVersion: number | null;
    members: MemberRow[];
    health: HealthRow[];
  };
};
export type GrantsRead = { network: NetworkChoice; grants: GrantRow[] };
export type ListingsRead = { network: NetworkChoice; listings: ListingRow[] };

/** The query of a BFF call that is about the network the page chose: empty when the server picks. */
export const queryFor = (networkId: string | null): string => (networkId === null ? '' : `?networkId=${encodeURIComponent(networkId)}`);

/** One write. `query` is the network choice and nothing else. */
export function post<T = unknown>(path: string, query: string, body?: unknown): Promise<BffResult<T>> {
  return bffRequest<T>(`${path}${query}`, { method: 'POST', body });
}

export type Notice = { ok: boolean; text: string };

/** A line the page says about the last thing it did: `status` when it worked, `alert` when it did not. */
export function useNotice(): { notice: Notice | null; say: (ok: boolean, text: string) => void; clear: () => void } {
  const [notice, setNotice] = useState<Notice | null>(null);
  const say = useCallback((ok: boolean, text: string) => setNotice({ ok, text }), []);
  const clear = useCallback(() => setNotice(null), []);
  return { notice, say, clear };
}

// ---------------------------------------------------------------- the member's sharing page (TEN-081)

export const SHARING_BASE = '/api/bff/sharing';

export type SharingPageNetwork = {
  id: string;
  name: string;
  isOwner: boolean;
  membershipStatus: 'invited' | 'active' | 'left' | 'removed';
  joinedAt: string | null;
  leftAt: string | null;
  agreementReference: string | null;
  agreementVersion: number | null;
  acceptedAgreementVersion: number | null;
  agreementBehind: boolean;
  shared: import('./views').KindState[];
  grants: GrantRow[];
};
export type SharingPage = {
  /** The organisation's own code, for its own administrator to give to the network owner. */
  organisationCode: string;
  allowlist: import('./views').Allowlist;
  networks: SharingPageNetwork[];
};
