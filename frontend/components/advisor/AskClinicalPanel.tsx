'use client';

import { useEffect, useState } from 'react';
import { bffFetch } from '@/lib/advisor/browser';
import { AGE_BANDS, labelOf, NEEDS, URGENCIES, type CaseView } from '@/lib/advisor/codes';
import { AskClinicalDialog, type CaseSummary } from './AskClinicalDialog';

// "Ask a clinical advisor" from a case screen (W45): reads the case itself and opens the dialog with a
// summary of it. The options list, the no-fit state and the map's postcode states all open this, so none of
// them has to hold the case. The summary shows the postcode district only, never the full postcode. A case
// that cannot be read does not stop the request: the dialog says the summary could not be read.

/** The case as the dialog's two lines: what is recorded, and nothing made up for what is not. */
export function summaryOfCase(view: CaseView): CaseSummary {
  const news2 = view.scores.find((score) => score.method === 'news2');
  const cfs = view.scores.find((score) => score.method === 'cfs');
  return {
    ageBand: labelOf(AGE_BANDS, view.ageBand),
    district: view.postcode === null ? null : (view.postcode.trim().split(/\s+/)[0] ?? null),
    needs: view.needs.map((code) => NEEDS.find((need) => need.code === code)?.short ?? code),
    within: labelOf(URGENCIES, view.urgency),
    news2: news2?.method === 'news2' ? news2.value : null,
    frailtyScale: cfs?.method === 'cfs' ? cfs.value : null,
  };
}

export function AskClinicalPanel({ caseRef, optionsShown, onClose }: { caseRef: string; optionsShown: number; onClose: () => void }) {
  // undefined: not read yet; null: could not be read.
  const [summary, setSummary] = useState<CaseSummary | null | undefined>(undefined);

  useEffect(() => {
    let live = true;
    bffFetch<CaseView>(`/api/bff/cases/${encodeURIComponent(caseRef)}`).then((reply) => {
      if (live) setSummary(reply.ok ? summaryOfCase(reply.body) : null);
    });
    return () => {
      live = false;
    };
  }, [caseRef]);

  if (summary === undefined) return <p role="status">Opening.</p>;
  return <AskClinicalDialog caseRef={caseRef} summary={summary} optionsShown={optionsShown} onClose={onClose} />;
}
