import { AGE_BANDS, type CaseView, labelOf, NEEDS, REFERRERS, URGENCIES } from './codes';
import { CFS_LABELS, MANCHESTER_TRIAGE, type Score } from './scores';

// The SystmOne summary (W15): the case as display strings, one row per field. Pure.
// Destination, booking and data age are not in the back end's answer yet, so they say so.

export const NOT_RECORDED = 'Not recorded in this view';
const NONE_GIVEN = 'None given';

export type SummaryView = {
  reference: string;
  referrer: string;
  ageBand: string;
  postcode: string;
  needs: string;
  urgency: string;
  scores: string;
  destination: string;
  booked: string;
  dataAge: string;
};

const SUMMARY_ROWS: readonly { key: keyof SummaryView; label: string }[] = [
  { key: 'referrer', label: 'Referrer' },
  { key: 'ageBand', label: 'Age band' },
  { key: 'postcode', label: 'Postcode' },
  { key: 'needs', label: 'Needs' },
  { key: 'urgency', label: 'Urgency' },
  { key: 'scores', label: 'Scores' },
  { key: 'destination', label: 'Destination' },
  { key: 'booked', label: 'Booked' },
  { key: 'dataAge', label: 'Data age' },
];

export function scoreText(score: Score): string {
  switch (score.method) {
    case 'news2':
      return `NEWS2 ${score.value}`;
    case 'cfs':
      return `Frailty scale ${score.value} · ${CFS_LABELS[score.value]}`;
    case 'ambulance-category':
      return `Ambulance category ${score.value}`;
    case 'manchester':
      return `Manchester triage ${labelOf(MANCHESTER_TRIAGE, score.value) ?? score.value}`;
    case 'pathways-dx':
      return `NHS Pathways Dx ${score.value}`;
  }
}

export function summaryOf(view: CaseView): SummaryView {
  const needs = view.needs
    .map((code) => NEEDS.find((need) => need.code === code)?.short ?? code)
    .join(', ');
  return {
    reference: view.reference ?? NOT_RECORDED,
    referrer: labelOf(REFERRERS, view.referrerType) ?? NOT_RECORDED,
    ageBand: labelOf(AGE_BANDS, view.ageBand) ?? NOT_RECORDED,
    postcode: view.postcode ?? NOT_RECORDED,
    needs: needs === '' ? NOT_RECORDED : needs,
    urgency: labelOf(URGENCIES, view.urgency) ?? NOT_RECORDED,
    scores: view.scores.length === 0 ? NONE_GIVEN : view.scores.map(scoreText).join('; '),
    destination: NOT_RECORDED,
    booked: NOT_RECORDED,
    dataAge: NOT_RECORDED,
  };
}

/** The summary as plain text for the referral: one row per line, "Label: value". */
export function summaryText(summary: SummaryView): string {
  return SUMMARY_ROWS.map((row) => `${row.label}: ${summary[row.key]}`).join('\n');
}

export const SUMMARY_LABELS = SUMMARY_ROWS;
