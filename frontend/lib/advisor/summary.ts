import { labelOf } from './codes';
import { CFS_LABELS, MANCHESTER_TRIAGE, type Score } from './scores';

// The SystmOne summary (W15): the case as display strings, one row per field. Pure.
// The back end builds the rows (BuildCaseSummary) so the text that is pasted is the text it holds.

export const NOT_RECORDED = 'Not recorded';
export const NO_DESTINATION = 'No destination chosen yet';
export const NOT_BOOKED = 'Not booked';
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

type Row = { name?: unknown; valueString?: unknown; part?: unknown };

/** The (label, text) rows of the back end's summary. A row whose label or value is not text is dropped. */
function rowsOf(parameters: Row[]): Map<string, string> {
  const rows = new Map<string, string>();
  for (const item of parameters) {
    if (item.name !== 'row' || !Array.isArray(item.part)) continue;
    const parts = item.part as Row[];
    const label = parts.find((part) => part.name === 'label')?.valueString;
    const value = parts.find((part) => part.name === 'value')?.valueString;
    if (typeof label === 'string' && typeof value === 'string' && !rows.has(label)) rows.set(label, value);
  }
  return rows;
}

/**
 * The summary the back end builds for an open case (BuildCaseSummary, H-322): the case number and one row
 * per field, in order, a field with nothing to say left out. `destinationNamed` is true when the request
 * named the service the call went to: its name, booking and data age are then rows of their own; without
 * one the three say no destination is chosen (never blank, never a guess). Null when the answer is not a
 * summary, so the route can say it could not be read.
 */
export function summaryFromParameters(value: unknown, destinationNamed: boolean): SummaryView | null {
  if (typeof value !== 'object' || value === null) return null;
  const resource = value as { resourceType?: unknown; parameter?: unknown };
  if (resource.resourceType !== 'Parameters' || !Array.isArray(resource.parameter)) return null;
  const parameters = resource.parameter as Row[];
  const reference = parameters.find((item) => item.name === 'reference')?.valueString;
  if (typeof reference !== 'string' || reference === '') return null;
  const rows = rowsOf(parameters);
  const absent = destinationNamed ? undefined : NO_DESTINATION;
  return {
    reference,
    referrer: rows.get('Referrer') ?? NOT_RECORDED,
    ageBand: rows.get('Age band') ?? NOT_RECORDED,
    postcode: rows.get('Postcode') ?? NOT_RECORDED,
    needs: rows.get('Needs') ?? NOT_RECORDED,
    urgency: rows.get('Urgency') ?? NOT_RECORDED,
    scores: rows.get('Scores') ?? NONE_GIVEN,
    destination: rows.get('Destination') ?? absent ?? NOT_RECORDED,
    booked: rows.get('Booked') ?? absent ?? NOT_BOOKED,
    dataAge: rows.get('Data age') ?? absent ?? NOT_RECORDED,
  };
}

/** The summary as plain text for the referral: one row per line, "Label: value". */
export function summaryText(summary: SummaryView): string {
  return SUMMARY_ROWS.map((row) => `${row.label}: ${summary[row.key]}`).join('\n');
}

export const SUMMARY_LABELS = SUMMARY_ROWS;
