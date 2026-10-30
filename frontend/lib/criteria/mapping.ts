import type { CriteriaOverview, CriteriaValues, NeedCode, PendingChange } from './types';

// The owner's and the approver's criteria reads, mapped from the back end's answers (W7B A4) to the
// shapes the criteria pages use (DEC-908). Pure: the BFF maps and the tests read the same rule. A
// version's author is a role; no person's name or id is kept. The overview's waiting change carries no
// values (the back end gives none there), so none are shown for it. Each mapper answers null for an
// answer that is not the shape the page needs, and the route answers 503.

type Json = Record<string, unknown>;

function isRecord(value: unknown): value is Json {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function text(value: unknown): string | undefined {
  return typeof value === 'string' && value !== '' ? value : undefined;
}

/** Need codes from a list of codes or of { code, label } items; a non-list is no codes. */
function codesOf(value: unknown): NeedCode[] | undefined {
  if (!Array.isArray(value)) return undefined;
  const codes: string[] = [];
  for (const item of value) {
    const code = typeof item === 'string' ? item : isRecord(item) ? text(item.code) : undefined;
    if (code === undefined) return undefined;
    codes.push(code);
  }
  return codes as NeedCode[];
}

function valuesOf(version: Json): (CriteriaValues & { version: number; reviewBy: string }) | null {
  const accepts = codesOf(version.accepts);
  const excludes = codesOf(version.excludes);
  const reviewBy = text(version.reviewBy);
  const ageMin = version.ageMin;
  const ageMax = version.ageMax;
  const districts = Array.isArray(version.districts) && version.districts.every((d) => typeof d === 'string') ? (version.districts as string[]) : undefined;
  if (
    typeof version.version !== 'number' ||
    !Number.isInteger(version.version) ||
    reviewBy === undefined ||
    accepts === undefined ||
    excludes === undefined ||
    districts === undefined ||
    typeof ageMin !== 'number' ||
    !(ageMax === null || typeof ageMax === 'number')
  ) {
    return null;
  }
  return { version: version.version, reviewBy, accepts, excludes, ageMin, ageMax, districts };
}

export function criteriaOverviewFromBackend(raw: unknown): CriteriaOverview | null {
  if (!isRecord(raw)) return null;
  const serviceName = text(raw.serviceName);
  if (serviceName === undefined || !isRecord(raw.current)) return null;
  const current = valuesOf(raw.current);
  if (current === null) return null;

  const view: CriteriaOverview = { serviceName, current };
  if (isRecord(raw.draft)) {
    const values = valuesOf(raw.draft);
    if (values === null) return null;
    const note = text(raw.draft.changeReason);
    const sentAt = text(raw.draft.changedOn);
    view.draft = {
      ...values,
      status: 'sent-back',
      ...(sentAt !== undefined ? { sentAt } : {}),
      ...(note !== undefined ? { note } : {}),
    };
  } else if (isRecord(raw.pending)) {
    const version = raw.pending.version;
    const sentAt = text(raw.pending.changedOn);
    if (typeof version !== 'number' || !Number.isInteger(version)) return null;
    view.draft = {
      version,
      reviewBy: current.reviewBy,
      status: 'waiting',
      ...(sentAt !== undefined ? { sentAt } : {}),
    };
  }
  if (raw.overdue === true) {
    const since = text(raw.overdueSince);
    if (since !== undefined) view.overdueSince = since;
  }
  if (isRecord(raw.shiftLead)) {
    const role = text(raw.shiftLead.label);
    const phone = text(raw.shiftLead.phone);
    if (role !== undefined && phone !== undefined) view.shiftLead = { role, phone };
  }
  return view;
}

export function pendingFromBackend(raw: unknown): PendingChange | null {
  if (!isRecord(raw)) return null;
  const taskId = text(raw.criteriaId);
  const serviceName = text(raw.serviceName);
  const authorRole = text(raw.authorRole);
  if (taskId === undefined || serviceName === undefined || authorRole === undefined || typeof raw.isAuthor !== 'boolean') return null;
  const reason = text(raw.changeReason) ?? '';

  let changes: string[] | null;
  if (raw.changes === null) {
    changes = null;
  } else if (Array.isArray(raw.changes)) {
    const words: string[] = [];
    for (const change of raw.changes) {
      const line = isRecord(change) ? text(change.words) : undefined;
      if (line === undefined) return null;
      words.push(line);
    }
    changes = words;
  } else {
    return null;
  }

  const view: PendingChange = { serviceName, taskId, isAuthor: raw.isAuthor, changes, reason, authorRole };
  if (changes === null) {
    if (!isRecord(raw.criteria)) return null;
    const values = valuesOf({ ...raw.criteria, version: raw.version, reviewBy: raw.criteria.reviewBy });
    if (values === null) return null;
    view.full = { ...values, ownerRole: text(raw.criteria.ownerRole) ?? authorRole };
  }
  return view;
}
