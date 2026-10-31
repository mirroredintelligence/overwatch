import type { IncomingMessage, ServerResponse } from 'node:http';
import { ACKNOWLEDGED_ALERT_TASKS, CLOSED_ALERT_TASKS, LEADER_PRACTITIONERS, OPEN_ALERT_TASKS } from '@/test/msw/handlers/exec';

// The executive's routes of the stand-in back end, for the browser tests (W39 to W41, W51): the alert lists
// (`GET /fhir/Task?code=acknowledge-alert`), an acknowledgement or snooze, the saved alert preferences, the
// leaders a deputy is chosen from, the week summary and the planning view. The shapes are the ones the
// unit tests' stand-in (test/msw/handlers/exec.ts) uses, so the pages read what the real routes send. It
// keeps the saved Subscription in memory for the process; a spec that writes one uses its own state.

const SETTING = 'https://overwatch.mirroredintelligence.com/CodeSystem/alert-preferences';
const SUBSCRIBER_ID = 'pr-0042';

const NEVER_SAVED = {
  resourceType: 'Subscription',
  id: SUBSCRIBER_ID,
  meta: { versionId: '1' },
  status: 'active',
  reason: 'Alert preferences of a shift lead or an executive',
  criteria: 'alert-preferences',
  channel: { type: 'message' },
  extension: [
    { url: `${SETTING}/kind`, valueCode: 'service-closed' },
    { url: `${SETTING}/kind`, valueCode: 'over-capacity' },
    { url: `${SETTING}/kind`, valueCode: 'not-updated' },
    { url: `${SETTING}/kind`, valueCode: 'system-pressure' },
    { url: `${SETTING}/not-updated-hours`, valueInteger: 2 },
    { url: `${SETTING}/ack-minutes`, valueInteger: 15 },
    { url: `${SETTING}/quiet-critical-only`, valueBoolean: true },
    { url: `${SETTING}/daily-summary`, valueBoolean: true },
    { url: `${SETTING}/weekly-summary`, valueBoolean: false },
  ],
};

const figure = (name: string, value: number) => ({ name, part: [{ name: 'suppressed', valueBoolean: false }, { name: 'value', valueInteger: value }] });

const WEEK = {
  resourceType: 'Parameters',
  parameter: [
    { name: 'weekStart', valueDate: '2026-10-19' },
    figure('referrals', 640),
    figure('bestFitUnavailablePct', 18),
    figure('onTimePct', 92),
    figure('medianMinutesToConfirmed', 4),
    { name: 'updatesByChannel', part: [{ name: 'text', part: [{ name: 'suppressed', valueBoolean: false }, { name: 'value', valueInteger: 412 }] }] },
  ],
};

// `GET /planning` (routes_planning.py): a count under 10 is null and suppressed.
const PLANNING = {
  cohort: 'Cohort: age 65+, falls and frailty, within 2 hrs, ambulance crew or care home referrers. Groups under 10 are hidden.',
  referrals: { count: 640, suppressed: false },
  bestFitUnavailable: { count: 112, pct: 18, suppressed: false },
  wentElsewhere: { count: 62, suppressed: false },
  flows: [
    { bestFit: 'Hospital at home', state: 'full', wentTo: 'UCR West', count: 18, suppressed: false },
    { bestFit: 'Hospital at home', state: 'full', wentTo: 'Emergency department', count: null, suppressed: true },
    { bestFit: 'UCR East', state: 'closed', wentTo: 'SDEC · Site 1', count: 22, suppressed: false },
  ],
  grid: [
    [null, null, 12, null],
    [null, null, 11, null],
    [null, 10, 14, null],
    [null, 12, 18, 10],
    [null, 11, 15, 12],
    [null, null, 11, 13],
    [null, null, null, 10],
  ],
  busiest: { day: 3, band: 2, count: 18 },
  declinedDespite: [
    { service: 'Community hospital · Ward A', count: 14, suppressed: false },
    { service: 'SDEC · Site 1', count: 11, suppressed: false },
    { service: 'UCR East', count: 10, suppressed: false },
  ],
};

let saved: Record<string, unknown> | null = null;

function send(response: ServerResponse, status: number, body: unknown, headers: Record<string, string> = {}) {
  response
    .writeHead(status, { 'Content-Type': 'application/fhir+json', 'Cache-Control': 'no-store', ...headers })
    .end(JSON.stringify(body));
}

function readBody(request: IncomingMessage): Promise<unknown> {
  return new Promise((resolve) => {
    const chunks: Buffer[] = [];
    request.on('data', (chunk: Buffer) => chunks.push(chunk));
    request.on('end', () => {
      try {
        resolve(JSON.parse(Buffer.concat(chunks).toString('utf8')));
      } catch {
        resolve(undefined);
      }
    });
  });
}

const bundle = (resources: readonly unknown[]) => ({ resourceType: 'Bundle', type: 'searchset', total: resources.length, entry: resources.map((resource) => ({ resource })) });

/** True for a request this stand-in answers; the caller routes it here before the advisor's `/fhir/Task` branch. */
export function isExecRoute(method: string | undefined, url: URL): boolean {
  const path = url.pathname;
  if (path === '/planning' || path === '/fhir/Practitioner' || path === '/fhir/HealthcareService/$week-summary') return true;
  if (path === '/fhir/Subscription' || /^\/fhir\/Subscription\/[^/]+$/.test(path)) return true;
  if (path === '/fhir/Task' && method === 'GET') return url.searchParams.get('code') === 'acknowledge-alert';
  return method === 'POST' && /^\/fhir\/Task\/[^/]+\/\$(acknowledge|snooze)$/.test(path);
}

export async function handleExecRoute(request: IncomingMessage, response: ServerResponse, url: URL): Promise<boolean> {
  const path = url.pathname;
  const method = request.method ?? 'GET';
  if (path === '/planning') {
    send(response, 200, PLANNING);
  } else if (path === '/fhir/HealthcareService/$week-summary') {
    send(response, 200, WEEK);
  } else if (path === '/fhir/Practitioner') {
    send(response, 200, bundle(LEADER_PRACTITIONERS));
  } else if (path === '/fhir/Task' && method === 'GET') {
    const status = url.searchParams.get('status');
    send(response, 200, bundle(status === 'acknowledged' ? ACKNOWLEDGED_ALERT_TASKS : status === 'closed' ? CLOSED_ALERT_TASKS : OPEN_ALERT_TASKS));
  } else if (path.endsWith('/$acknowledge')) {
    await readBody(request);
    send(response, 200, { resourceType: 'Task', id: path.split('/')[3], businessStatus: { coding: [{ code: 'acknowledged' }] } });
  } else if (path.endsWith('/$snooze')) {
    await readBody(request);
    send(response, 200, {
      resourceType: 'Parameters',
      parameter: [
        { name: 'alertId', valueString: path.split('/')[3] },
        { name: 'escalationDueAt', valueDateTime: '2026-10-23T14:19:00Z' },
      ],
    });
  } else if (path === '/fhir/Subscription' && method === 'GET') {
    send(response, 200, bundle([saved ?? NEVER_SAVED]));
  } else if (/^\/fhir\/Subscription\/[^/]+$/.test(path) && method === 'PUT') {
    const payload = (await readBody(request)) as Record<string, unknown> | undefined;
    const version = String(Date.now());
    saved = { ...(payload ?? {}), id: path.split('/')[3], meta: { versionId: version } };
    send(response, 200, saved, { ETag: `W/"${version}"` });
  } else {
    return false;
  }
  return true;
}
