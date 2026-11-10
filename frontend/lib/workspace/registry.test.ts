import { readFileSync } from 'node:fs';
import path from 'node:path';
import { expect, it } from 'vitest';
import { canAccess } from '@/lib/auth/access';
import type { Role } from '@/lib/auth/session';
import registryJson from './registry.json';
import { canOpen, identityOf, intentById, intentsFor, routeOf, type Intent } from './registry';

// Expectation tables, written out from docs/design/workspaces/screens.md (WS-MATRIX), not read from registry.json.

const IDENTITY: Record<string, { persona: string; flags: string[]; workspace: boolean }> = {
  advisor: { persona: 'advisor', flags: [], workspace: true },
  'advisor-v2': { persona: 'advisor', flags: [], workspace: true },
  clinical: { persona: 'advisor', flags: ['clinicalSignOff'], workspace: false },
  'analytics-user': { persona: 'overview', flags: [], workspace: true },
  lead: { persona: 'manager', flags: ['peopleAndPhones', 'planningAndAlerts', 'auditReplay'], workspace: false },
  exec: { persona: 'manager', flags: ['planningAndAlerts'], workspace: false },
  owner: { persona: 'manager', flags: ['ownCriteria'], workspace: false },
  audit: { persona: 'manager', flags: ['auditReplay'], workspace: false },
  reporter: { persona: 'reporter', flags: [], workspace: false },
  'tenant-admin': { persona: 'admin', flags: [], workspace: false },
  'network-admin': { persona: 'admin', flags: [], workspace: false },
  support: { persona: 'platform', flags: [], workspace: false },
  wall: { persona: 'display', flags: [], workspace: false },
  'anonymous-link': { persona: 'display', flags: [], workspace: false },
};

const ADVISOR_NOW = [
  'advisor.intake.age',
  'advisor.intake.need',
  'advisor.results',
  'advisor.service',
  'advisor.new-search',
];

const NOW: Record<string, string[]> = {
  advisor: ADVISOR_NOW,
  'advisor-v2': ADVISOR_NOW,
  clinical: [],
  'analytics-user': ['overview.home', 'overview.attention', 'overview.area'],
  lead: [],
  exec: [],
  owner: [],
  audit: [],
  reporter: [],
  'tenant-admin': [],
  'network-admin': [],
  support: [],
  wall: [],
  'anonymous-link': [],
};

const ADVISOR_ALL = [
  'advisor.intake.age',
  'advisor.intake.need',
  'advisor.results',
  'advisor.map',
  'advisor.reasons',
  'advisor.service',
  'advisor.new-search',
];

const ADMIN_ALL = [
  'go.admin.access',
  'go.admin.users',
  'go.admin.config',
  'go.admin.contacts',
  'go.admin.email',
  'go.admin.retention',
  'go.admin.sharing',
  'go.admin.support',
];

const ALL: Record<string, string[]> = {
  advisor: ADVISOR_ALL,
  'advisor-v2': ADVISOR_ALL,
  clinical: [],
  'analytics-user': ['overview.home', 'overview.attention', 'overview.area'],
  lead: ['go.people-and-phones', 'go.planning', 'go.audit-replay'],
  exec: ['go.planning'],
  owner: ['go.criteria'],
  audit: [],
  reporter: [],
  'tenant-admin': ADMIN_ALL,
  'network-admin': [],
  support: [],
  wall: [],
  'anonymous-link': [],
};

// Every intent id in registry order (the 22 ids of WS-MATRIX).
const ALL_IDS = [
  'advisor.intake.age',
  'advisor.intake.need',
  'advisor.results',
  'advisor.map',
  'advisor.reasons',
  'advisor.service',
  'advisor.new-search',
  'overview.home',
  'overview.attention',
  'overview.area',
  'go.people-and-phones',
  'go.planning',
  'go.criteria',
  'go.audit-replay',
  'go.admin.access',
  'go.admin.users',
  'go.admin.config',
  'go.admin.contacts',
  'go.admin.email',
  'go.admin.retention',
  'go.admin.sharing',
  'go.admin.support',
];

function must(id: string): Intent {
  const found = intentById(id);
  if (!found) throw new Error(`no intent ${id}`);
  return found;
}

it('WS-REG-T01 identityOf maps each of the 14 session roles to its persona, flags and workspace value, and nobody to null', () => {
  expect(Object.keys(IDENTITY)).toHaveLength(14);
  for (const role of Object.keys(IDENTITY)) {
    expect(identityOf(role), role).toEqual(IDENTITY[role]);
  }
  expect(identityOf('nobody')).toBeNull();
});

it('WS-REG-T02 intentsFor(role) equals the Now column of WS-MATRIX for all 14 roles, ids in order', () => {
  expect(Object.keys(NOW)).toHaveLength(14);
  for (const role of Object.keys(NOW)) {
    expect(intentsFor(role).map((intent) => intent.id), role).toEqual(NOW[role]);
  }
});

it('WS-REG-T03 intentsFor(role, { phase: 99 }) equals the All column of WS-MATRIX for all 14 roles', () => {
  expect(Object.keys(ALL)).toHaveLength(14);
  for (const role of Object.keys(ALL)) {
    expect(intentsFor(role, { phase: 99 }).map((intent) => intent.id), role).toEqual(ALL[role]);
  }
});

it('WS-REG-T04 canOpen(role, id) is true exactly when id is in intentsFor(role); unknown role or intent is false; phase is respected', () => {
  for (const role of Object.keys(NOW)) {
    for (const id of ALL_IDS) {
      expect(canOpen(role, id), `${role} ${id}`).toBe(NOW[role].includes(id));
      expect(canOpen(role, id, { phase: 99 }), `${role} ${id} phase 99`).toBe(ALL[role].includes(id));
    }
  }
  expect(canOpen('nobody', 'advisor.results')).toBe(false);
  expect(canOpen('advisor', 'nope')).toBe(false);
  expect(canOpen('advisor', 'advisor.map')).toBe(false);
  expect(canOpen('advisor', 'advisor.map', { phase: 4 })).toBe(true);
  expect(canOpen('advisor', 'advisor.results', { phase: 0 })).toBe(false);
  expect(canOpen('lead', 'go.planning')).toBe(false);
  expect(canOpen('lead', 'go.planning', { phase: 3 })).toBe(true);
});

it('WS-REG-T05 every intent and session role that canOpen offers at phase 99 is allowed by the route guard canAccess', () => {
  let checked = 0;
  for (const entry of registryJson.intents) {
    const intent = must(entry.id);
    for (const role of Object.keys(IDENTITY)) {
      if (!canOpen(role, intent.id, { phase: 99 })) continue;
      checked += 1;
      expect(canAccess(role as Role, routeOf(intent, { id: 'x' })), `${role} ${intent.id}`).toBe(true);
    }
  }
  // The number of (role, intent) pairs the WS-MATRIX "All" column offers: 30.
  expect(checked).toBe(30);
});

it('WS-REG-T06 intent ids are unique, layouts, personas and requires refer to keys that exist', () => {
  const ids = registryJson.intents.map((intent) => intent.id);
  expect(new Set(ids).size).toBe(ids.length);
  const layouts = Object.keys(registryJson.layouts);
  const personas = Object.keys(registryJson.personas);
  for (const intent of registryJson.intents) {
    if (intent.layout !== null) expect(layouts, intent.id).toContain(intent.layout);
    for (const persona of intent.personas) expect(personas, intent.id).toContain(persona);
    if (intent.requires !== null) expect(registryJson.flags, intent.id).toContain(intent.requires);
  }
});

it('WS-REG-T07 the runtime registry.json deep-equals docs/design/workspaces/registry.json', () => {
  const docPath = path.resolve(process.cwd(), '..', 'docs/design/workspaces/registry.json');
  const doc: unknown = JSON.parse(readFileSync(docPath, 'utf8'));
  expect(registryJson).toEqual(doc);
});

it('WS-REG-T08 routeOf replaces [id], throws without an id, and returns other routes unchanged', () => {
  const service: Intent = {
    id: 'test.service', label: 'Service', kind: 'view', phase: 1,
    personas: ['advisor'], requires: null, dataClass: 'patient',
    route: '/advisor/v2/services/[id]', params: {}, layout: 'detail',
  };
  expect(routeOf(service, { id: 'svc-1' })).toBe('/advisor/v2/services/svc-1');
  expect(() => routeOf(service)).toThrow(new Error('routeOf: missing id'));
  expect(() => routeOf(service, {})).toThrow(new Error('routeOf: missing id'));
  const results = must('advisor.results');
  expect(routeOf(results)).toBe('/advisor/v2');
  expect(routeOf(results, { id: 'svc-1' })).toBe('/advisor/v2');
});
