import { type AuditReplay, ReplayShapeError } from './audit';

// The browser's reading of the replay the BFF answers. It checks the shape the page needs, and refuses
// anything else (a partly read replay is not shown).

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

export function parseReplayAnswer(value: unknown): AuditReplay {
  const body = obj(value);
  if (typeof body.chainOk !== 'boolean') throw new ReplayShapeError();
  return {
    reference: str(body.reference),
    decisionAt: str(body.decisionAt),
    chainOk: body.chainOk,
    shown: list(body.shown).map((item) => {
      const row = obj(item);
      return { serviceName: str(row.serviceName), status: str(row.status), value: str(row.value), age: str(row.age) };
    }),
    criteriaVersions: list(body.criteriaVersions).map((item) => {
      const row = obj(item);
      if (typeof row.version !== 'number') throw new ReplayShapeError();
      return { serviceName: str(row.serviceName), version: row.version };
    }),
    timeline: list(body.timeline).map((item) => {
      const row = obj(item);
      return { at: str(row.at), label: str(row.label) };
    }),
  };
}
