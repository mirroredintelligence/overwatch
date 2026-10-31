import { useCallback, useEffect, useRef, useState } from 'react';
import type { OptionsParts } from '@/lib/advisor/options';
import { readNetworkView } from './browser';
import { networkOptionsToParts, parseNetworkOptions } from './options';

// The advisor's network options, read for the list and the map (WB11). One read per case and network on
// mount, and again only when the advisor asks to try again: the back end keeps an audit entry for each read
// of what the advisor was shown, so a focus or a re-render must not read again. The network is the id the
// server offered; the case is the advisor's own reference, and nothing else of the case is sent.

export type NetworkOptionsState =
  | { kind: 'loading' }
  | { kind: 'ready'; parts: OptionsParts }
  | { kind: 'refused' }
  | { kind: 'failed' };

export function useNetworkOptions(networkId: string, caseId: string): { state: NetworkOptionsState; retry: () => void } {
  const [state, setState] = useState<NetworkOptionsState>({ kind: 'loading' });
  const requested = useRef<string | null>(null);

  const read = useCallback(async () => {
    const result = await readNetworkView('options', networkId, (body) => parseNetworkOptions(body, 'bff'), `case=${encodeURIComponent(caseId)}`);
    if (result.ok) setState({ kind: 'ready', parts: networkOptionsToParts(result.data) });
    // Any refusal is the one "not available": a case that is not here, a network not offered, a role not let in.
    else setState([401, 403, 404].includes(result.status) ? { kind: 'refused' } : { kind: 'failed' });
  }, [networkId, caseId]);

  useEffect(() => {
    const key = `${networkId}:${caseId}`;
    // One read per network and case. Re-running the effect (a strict-mode remount) does not read again.
    if (requested.current === key) return;
    requested.current = key;
    void read();
  }, [networkId, caseId, read]);

  const retry = useCallback(() => {
    setState({ kind: 'loading' });
    void read();
  }, [read]);

  return { state, retry };
}
