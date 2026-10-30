// The audit replay (W47): what the advisor saw at the decision, for one case reference. The back end's
// answer (snake_case, U42) is read here and given to the pages in the BFF's shape. A shape that is not the
// one expected is an error, never a replay with parts missing.

import type { StatusCode } from '@/components/ui/StatusBadge';

export type ReplayShown = { serviceName: string; status: string; value: string; age: string };
export type ReplayCriteria = { serviceName: string; version: number };
export type ReplayTimelineItem = { at: string; label: string };

export type AuditReplay = {
  reference: string;
  decisionAt: string;
  chainOk: boolean;
  shown: ReplayShown[];
  criteriaVersions: ReplayCriteria[];
  timeline: ReplayTimelineItem[];
};

export class ReplayShapeError extends Error {
  constructor() {
    super('The audit replay was not the one expected.');
    this.name = 'ReplayShapeError';
  }
}

type Json = Record<string, unknown>;

function obj(value: unknown): Json {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) throw new ReplayShapeError();
  return value as Json;
}

function str(value: unknown): string {
  if (typeof value !== 'string') throw new ReplayShapeError();
  return value;
}

function list(value: unknown): unknown[] {
  if (!Array.isArray(value)) throw new ReplayShapeError();
  return value;
}

/** The BFF's replay from the back end's answer (U42, as ExportAuditReplay writes it). */
export function replayFromBackEnd(value: unknown): AuditReplay {
  const body = obj(value);
  if (typeof body.chain_ok !== 'boolean') throw new ReplayShapeError();
  const rows = list(body.rows).map((row) => {
    const r = obj(row);
    return {
      serviceName: str(r.service_name),
      status: str(r.status),
      value: str(r.value_text),
      age: str(r.data_age_text),
      version: typeof r.criteria_version === 'number' ? r.criteria_version : null,
    };
  });
  return {
    reference: str(body.reference),
    decisionAt: str(body.shown_at),
    chainOk: body.chain_ok,
    shown: rows.map(({ serviceName, status, value: v, age }) => ({ serviceName, status, value: v, age })),
    criteriaVersions: rows
      .filter((r) => r.version !== null)
      .map((r) => ({ serviceName: r.serviceName, version: r.version as number })),
    timeline: list(body.timeline).map((item) => {
      const t = obj(item);
      return { at: str(t.at), label: str(t.label) };
    }),
  };
}

const WORDS: Record<string, StatusCode> = {
  Accepting: 'accepting',
  Limited: 'limited',
  'Not accepting': 'not-accepting',
  'Over capacity': 'over-capacity',
  'Not updated': 'not-updated',
  'Out of hours': 'out-of-hours',
};

/** The badge code for a status word the back end gives, or null for a word the screen does not know. */
export function statusCodeFor(word: string): StatusCode | null {
  return WORDS[word] ?? null;
}
