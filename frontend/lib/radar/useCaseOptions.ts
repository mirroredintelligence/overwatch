'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { bffFetch } from '@/lib/advisor/browser';
import type { CaseView } from '@/lib/advisor/codes';
import { chooseDistrict } from '@/lib/advisor/district';
import type { OptionsParts } from '@/lib/advisor/options';

// The options of one case for the radar screens (RadarWeb): the same read the map makes, for the
// viewer's own services only (`?only=own`: the radar shows who in this organisation covers the patient;
// the network's services have their own pages), and the case's postcode for the heading. One read per
// load; a district chosen is saved on the case and the options are read again (W9H, DEC-1045).

export type CaseOptionsLoad =
  | { kind: 'loading' }
  | { kind: 'ready'; parts: OptionsParts; postcode: string | null; view: CaseView | null }
  | { kind: 'failed' };

export function useCaseOptions(caseId: string): {
  load: CaseOptionsLoad;
  retry: () => void;
  choose: (district: string) => Promise<boolean>;
} {
  const [load, setLoad] = useState<CaseOptionsLoad>({ kind: 'loading' });
  const requested = useRef<string | null>(null);
  const id = encodeURIComponent(caseId);

  const read = useCallback(async () => {
    const [options, caseRead] = await Promise.all([
      bffFetch<OptionsParts>(`/api/bff/cases/${id}/options?only=own`),
      bffFetch<CaseView>(`/api/bff/cases/${id}`),
    ]);
    if (!options.ok) {
      setLoad({ kind: 'failed' });
      return;
    }
    setLoad({
      kind: 'ready',
      parts: options.body,
      postcode: caseRead.ok ? caseRead.body.postcode : null,
      view: caseRead.ok ? caseRead.body : null,
    });
  }, [id]);

  useEffect(() => {
    if (requested.current === caseId) return;
    requested.current = caseId;
    void read();
  }, [caseId, read]);

  const retry = useCallback(() => {
    setLoad({ kind: 'loading' });
    void read();
  }, [read]);

  const choose = useCallback(
    async (district: string): Promise<boolean> => {
      if (!(await chooseDistrict(caseId, district))) return false;
      await read();
      return true;
    },
    [caseId, read],
  );

  return { load, retry, choose };
}
