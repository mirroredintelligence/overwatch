// The version history and the waiting version, read from the back end's history bundle (U30). Pure:
// the BFF maps a bundle with it, and the browser parses the BFF's answer with `parseHistory`.
import type { HistoryVersion } from './types';

type Json = Record<string, unknown>;

function isRecord(value: unknown): value is Json {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

const STATUS: Readonly<Record<string, HistoryVersion['status']>> = {
  'pending-approval': 'waiting',
  current: 'current',
  superseded: 'replaced',
  retired: 'retired',
};

/**
 * The versions of one service, newest first, from a searchset Bundle of Basic resources. A draft is
 * not a version of the history and is left out. A status the browser does not know is refused.
 */
export function mapHistory(bundle: unknown): HistoryVersion[] {
  if (!isRecord(bundle) || bundle.resourceType !== 'Bundle' || !Array.isArray(bundle.entry)) {
    throw new Error('the history is not a bundle');
  }
  const versions: HistoryVersion[] = [];
  for (const entry of bundle.entry as unknown[]) {
    const resource = isRecord(entry) && isRecord(entry.resource) ? entry.resource : undefined;
    if (resource === undefined || resource.resourceType !== 'Basic') throw new Error('the history holds a non-criteria entry');
    if (resource.status === 'draft') continue;
    const meta = isRecord(resource.meta) ? resource.meta : undefined;
    const version = typeof meta?.versionId === 'string' ? Number(meta.versionId) : NaN;
    const status = typeof resource.status === 'string' ? STATUS[resource.status] : undefined;
    if (!Number.isInteger(version) || status === undefined || typeof resource.id !== 'string') {
      throw new Error('a version in the history cannot be read');
    }
    versions.push({
      version,
      status,
      reviewBy: typeof resource.reviewBy === 'string' ? resource.reviewBy : '',
      criteriaId: resource.id,
    });
  }
  return versions.sort((a, b) => b.version - a.version);
}

/** The version waiting for its second approval, or null when none is. */
export function waitingVersion(versions: readonly HistoryVersion[]): HistoryVersion | null {
  return versions.find((version) => version.status === 'waiting') ?? null;
}

/** The browser's history answer, as the BFF sends it. The criteria id stays on the server. */
export function parseHistory(value: unknown): { versions: HistoryVersion[] } {
  if (!isRecord(value) || !Array.isArray(value.versions)) throw new Error('expected a history');
  return {
    versions: (value.versions as unknown[]).map((item) => {
      if (!isRecord(item) || typeof item.version !== 'number' || typeof item.status !== 'string') {
        throw new Error('unexpected history line');
      }
      return {
        version: item.version,
        status: item.status as HistoryVersion['status'],
        reviewBy: typeof item.reviewBy === 'string' ? item.reviewBy : '',
        criteriaId: '',
      };
    }),
  };
}
