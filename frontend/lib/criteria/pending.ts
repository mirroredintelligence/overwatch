// The approver's read of the waiting change, as the browser parses it (W31). Shape only: who may
// approve, and what is shown to whom, is the back end's decision.
import { isNeedCode } from './model';
import type { NeedCode, PendingChange } from './types';

type Json = Record<string, unknown>;

function record(value: unknown): Json {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) throw new Error('expected an object');
  return value as Json;
}

function text(value: unknown): string {
  if (typeof value !== 'string') throw new Error('expected a string');
  return value;
}

function whole(value: unknown): number {
  if (typeof value !== 'number' || !Number.isInteger(value)) throw new Error('expected a whole number');
  return value;
}

function needs(value: unknown): NeedCode[] {
  if (!Array.isArray(value) || !value.every(isNeedCode)) throw new Error('unexpected need');
  return value as NeedCode[];
}

function fullOf(value: unknown): NonNullable<PendingChange['full']> {
  const f = record(value);
  if (!Array.isArray(f.districts)) throw new Error('expected districts');
  return {
    accepts: needs(f.accepts),
    excludes: needs(f.excludes),
    ageMin: whole(f.ageMin),
    ageMax: f.ageMax === null || f.ageMax === undefined ? null : whole(f.ageMax),
    districts: f.districts.map(text),
    reviewBy: text(f.reviewBy),
    version: whole(f.version),
    ownerRole: text(f.ownerRole),
  };
}

export function parsePending(value: unknown): PendingChange {
  const body = record(value);
  if (typeof body.isAuthor !== 'boolean') throw new Error('expected a flag');
  const changes = body.changes === null ? null : Array.isArray(body.changes) ? body.changes.map(text) : undefined;
  if (changes === undefined) throw new Error('expected changes');
  const full = body.full === undefined || body.full === null ? undefined : fullOf(body.full);
  return {
    serviceName: text(body.serviceName),
    taskId: text(body.taskId),
    isAuthor: body.isAuthor,
    changes,
    ...(full !== undefined ? { full } : {}),
    reason: text(body.reason),
    authorRole: text(body.authorRole),
  };
}
