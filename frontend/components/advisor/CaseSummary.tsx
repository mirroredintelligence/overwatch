'use client';

import { useEffect, useState } from 'react';
import { bffFetch } from '@/lib/advisor/browser';
import type { CaseView } from '@/lib/advisor/codes';
import { CaseSummaryLine } from './CaseSummaryLine';

// The one-line summary of the case, read from the BFF (W13). Shows nothing when the case cannot be
// read: the options list does not depend on it.

export function CaseSummary({ caseId }: { caseId: string }) {
  const [view, setView] = useState<CaseView | null>(null);

  useEffect(() => {
    let live = true;
    bffFetch<CaseView>(`/api/bff/cases/${encodeURIComponent(caseId)}`).then((reply) => {
      if (live && reply.ok) setView(reply.body);
    });
    return () => {
      live = false;
    };
  }, [caseId]);

  if (view === null) return null;
  return (
    <CaseSummaryLine
      caseId={caseId}
      ageBand={view.ageBand}
      postcode={view.postcode}
      needs={view.needs}
      urgency={view.urgency}
    />
  );
}
