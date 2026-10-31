import type { IncomingMessage, ServerResponse } from 'node:http';
import { CASE_FULL } from '@/test/fixtures/backend-shapes';
import { RADAR_NOT_FOUND_PARAMETERS, RADAR_PARAMETERS } from '@/test/fixtures/radar';

// The radar and coverage routes of the stand-in back end, for the browser tests (RadarWeb, MapWeb).
//
// THE REAL BACK END DOES NOT SERVE THE COVERAGE ROUTES YET (lib/areas/types.ts holds the contract), so the
// shapes here are the contract, not a recording of the back end. The case routes are the real ones: the
// options of a case are the `$filter-options` Parameters the back end writes, and the cases below are the
// stand-in's own, so these tests never touch the one shared case of the advisor spec (e2e/support/advisor.ts):
//
//   radar-1   a case with a placed postcode: four options, three of them visiting and overlapping
//   radar-nf  a case whose postcode is not found, until a postcode is saved on it; then it is radar-1's

const NOT_FOUND = { resourceType: 'OperationOutcome', issue: [{ severity: 'error', code: 'not-found' }] };
export const RADAR_CASES = ['radar-1', 'radar-nf'] as const;

const state = { fixed: false, coverage: null as null | { districts: string[]; responseHours: number; days: string[] } };

function send(response: ServerResponse, status: number, body: unknown) {
  response.writeHead(status, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' }).end(JSON.stringify(body));
}

function read(request: IncomingMessage): Promise<string> {
  return new Promise((resolve) => {
    let text = '';
    request.on('data', (chunk: Buffer) => (text += chunk.toString()));
    request.on('end', () => resolve(text));
  });
}

/** The case id named in a `$filter-options` body (`ServiceRequest/<id>`), or null. */
export function caseOfOptionsBody(text: string): string | null {
  try {
    const body = JSON.parse(text) as { parameter?: { valueReference?: { reference?: string } }[] };
    return /^ServiceRequest\/(.+)$/.exec(body.parameter?.[0]?.valueReference?.reference ?? '')?.[1] ?? null;
  } catch {
    return null;
  }
}

export function isRadarCase(id: string | null | undefined): id is (typeof RADAR_CASES)[number] {
  return RADAR_CASES.some((known) => known === id);
}

/** The options of a radar case. */
export function radarOptions(caseId: (typeof RADAR_CASES)[number]) {
  return caseId === 'radar-nf' && !state.fixed ? RADAR_NOT_FOUND_PARAMETERS : RADAR_PARAMETERS;
}

/** The case a radar case id names: complete (needs, age, urgency, a district), so a postcode can be saved on it. */
export function radarCase(caseId: string) {
  return { ...CASE_FULL, id: caseId };
}

/** A save of the radar-nf case's postcode: the postcode is found from now on. */
export function postcodeSaved(caseId: string) {
  if (caseId === 'radar-nf') state.fixed = true;
}

const COVERAGE_BY_WINDOW: Record<string, { district: string; services: string[] }[]> = {
  all: [
    { district: 'DT1', services: ['UCR West'] },
    { district: 'DT2', services: ['UCR West'] },
    { district: 'DT3', services: ['UCR West', 'UCR East'] },
    { district: 'DT4', services: ['UCR West', 'UCR East'] },
    { district: 'DT5', services: [] },
    { district: 'DT6', services: [] },
  ],
  night: [
    { district: 'DT1', services: [] },
    { district: 'DT2', services: [] },
    { district: 'DT3', services: ['UCR East'] },
    { district: 'DT4', services: ['UCR East'] },
    { district: 'DT5', services: [] },
    { district: 'DT6', services: [] },
  ],
};

const FORM = {
  available: ['DT1', 'DT2', 'DT3', 'DT4', 'DT5', 'DT6'],
  others: [{ district: 'DT4', service: 'UCR East' }],
};

/** Answers the coverage routes (at the root, not under /fhir) and returns true; false for any other path. */
export async function handleRadarRoute(request: IncomingMessage, response: ServerResponse, pathname: string, search: URLSearchParams): Promise<boolean> {
  const form = /^\/lead\/services\/([^/]+)\/coverage$/.exec(pathname);
  if (pathname !== '/planning/coverage' && form === null) return false;
  if (request.headers.authorization === undefined) {
    send(response, 401, { resourceType: 'OperationOutcome', issue: [{ severity: 'error', code: 'login' }] });
    return true;
  }

  if (pathname === '/planning/coverage') {
    const window = search.get('window') ?? 'all';
    // Any part of the day that is not "night" reads like the whole day: the stand-in has two sample answers.
    const districts = COVERAGE_BY_WINDOW[window === 'night' ? 'night' : 'all'];
    send(response, 200, { window, districts, uncovered: { count: window === 'night' ? null : 31, suppressed: window === 'night', days: 90 } });
    return true;
  }

  if (form?.[1] !== 'svc-ucr-west') {
    send(response, 404, NOT_FOUND);
    return true;
  }
  if (request.method === 'PUT') {
    if (request.headers['idempotency-key'] === undefined) {
      send(response, 400, { resourceType: 'OperationOutcome', issue: [{ severity: 'error', code: 'invalid' }] });
      return true;
    }
    state.coverage = JSON.parse(await read(request)) as NonNullable<typeof state.coverage>;
  }
  const now = state.coverage ?? { districts: ['DT3', 'DT4'], responseHours: 2, days: ['mon', 'tue', 'wed', 'thu', 'fri'] };
  send(response, 200, { service: { id: 'svc-ucr-west', name: 'UCR West' }, ...FORM, ...now });
  return true;
}
