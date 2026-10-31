import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ROLES } from '../auth/session';
import { ALLOWED_ATTRIBUTES, ALLOWED_EVENTS, droppedEvents, flush, initTelemetry, stopTelemetry, track } from './events';
import { FRICTION_EVENT } from './friction';
import {
  COMMON_SCHEMA,
  EVENT_SCHEMAS,
  ROLE_VALUES,
  UI_EVENT_NAMES,
  isFreeText,
  validateEvent,
  type AttrSpec,
} from './schema';

// Every attribute spec the telemetry can send: the common ones and each event's own.
function allSpecs(): Array<[string, AttrSpec]> {
  const specs: Array<[string, AttrSpec]> = [];
  for (const [key, spec] of Object.entries(COMMON_SCHEMA)) specs.push([`common:${key}`, spec]);
  for (const name of UI_EVENT_NAMES) {
    for (const [key, spec] of Object.entries(EVENT_SCHEMAS[name])) specs.push([`${name}:${key}`, spec]);
  }
  return specs;
}

describe('the event list', () => {
  it('has a schema for every event the browser sends, including ui.friction', () => {
    expect(ALLOWED_EVENTS).toEqual([...UI_EVENT_NAMES]);
    for (const name of ALLOWED_EVENTS) {
      expect(Object.keys(EVENT_SCHEMAS)).toContain(name);
    }
    expect(ALLOWED_EVENTS).toContain(FRICTION_EVENT);
  });

  it('lists the same roles as the session module', () => {
    expect([...ROLE_VALUES]).toEqual([...ROLES]);
  });
});

describe('no free text', () => {
  it('no attribute spec in any schema is free text (the build-failing test)', () => {
    const free = allSpecs().filter(([, spec]) => isFreeText(spec)).map(([where]) => where);
    expect(free).toEqual([]);
  });

  it('flags a spec that could hold text a person typed', () => {
    expect(isFreeText({ type: 'id', pattern: /.*/ })).toBe(true);
    expect(isFreeText({ type: 'id', pattern: /^[A-Z ]+$/ })).toBe(true);
    expect(isFreeText({ type: 'enum', values: [] })).toBe(true);
    expect(isFreeText({ type: 'enum', values: ['a value with spaces in it'] })).toBe(true);
  });

  it('accepts numbers, booleans, fixed enums and anchored id patterns', () => {
    expect(isFreeText({ type: 'number' })).toBe(false);
    expect(isFreeText({ type: 'boolean' })).toBe(false);
    expect(isFreeText({ type: 'enum', values: ['on', 'off'] })).toBe(false);
    expect(isFreeText({ type: 'id', pattern: /^[A-Z0-9]+(-[A-Z0-9]+)*$/ })).toBe(false);
  });

  it('refuses every value of the probe the privacy rule names, in every string attribute', () => {
    for (const name of UI_EVENT_NAMES) {
      for (const [key, spec] of Object.entries(EVENT_SCHEMAS[name])) {
        if (spec.type === 'number' || spec.type === 'boolean') continue;
        const problems = validateEvent(name, { [key]: 'DT4 8XX' });
        expect(problems.length, `${name} ${key}`).toBeGreaterThan(0);
      }
    }
  });
});

describe('validateEvent', () => {
  it('accepts a ui.input with an element id, a validity flag and a length bucket', () => {
    expect(validateEvent('ui.input', { 'element.id': 'ADV-NEEDS-POSTCODE', valid: true, length_bucket: '6-20' })).toEqual(
      [],
    );
  });

  it('names the attribute that carries a typed value and does not repeat the value', () => {
    const problems = validateEvent('ui.input', {
      'element.id': 'ADV-NEEDS-POSTCODE',
      valid: true,
      length_bucket: '6-20',
      value: 'DT4 8XX',
    });

    expect(problems.length).toBeGreaterThan(0);
    expect(problems.join(' ')).toContain('value');
    expect(problems.join(' ')).not.toContain('DT4 8XX');
  });

  it('refuses an element id with a space in it', () => {
    const problems = validateEvent('ui.click', { 'element.id': 'adv opt', result: 'none' });

    expect(problems.join(' ')).toContain('element.id');
  });

  it('refuses an unknown event name', () => {
    expect(validateEvent('ui.typed_text', {}).length).toBeGreaterThan(0);
  });

  it('refuses a release that is not a three-part version', () => {
    expect(validateEvent('ui.page_view', { release: 'test-release-1', 'page.route': '/board' }).length).toBeGreaterThan(0);
    expect(validateEvent('ui.page_view', { release: '1.4.2', 'page.route': '/board' })).toEqual([]);
  });

  it('accepts the friction kinds and refuses a kind outside the list', () => {
    const friction = { 'element.id': 'PAGE', count: 3, window_ms: 1000 };
    expect(validateEvent('ui.friction', { ...friction, kind: 'rage' })).toEqual([]);
    expect(validateEvent('ui.friction', { ...friction, kind: 'anything the user typed' }).length).toBeGreaterThan(0);
  });
});

describe('route templates', () => {
  it('accepts a template whose parameter is named in camel case', () => {
    expect(validateEvent('ui.page_view', { 'page.route': '/app/respond/[serviceId]' })).toEqual([]);
    expect(validateEvent('ui.page_view', { 'page.route': '/criteria/[serviceId]/approve' })).toEqual([]);
    expect(validateEvent('ui.page_view', { 'page.route': '/' })).toEqual([]);
  });

  it('still refuses text a person could have typed in a route', () => {
    for (const route of ['/case/DT4 8XX', '/Sample Patient', '/a/[ref', '/Advisor/board', 'board', '/a/[re f]']) {
      expect(validateEvent('ui.page_view', { 'page.route': route }).length, route).toBeGreaterThan(0);
    }
  });
});

describe('ui.web_vital', () => {
  it('carries a metric from a fixed list, a number and a rating, and nothing that is free text', () => {
    for (const metric of ['lcp', 'inp', 'cls']) {
      expect(validateEvent('ui.web_vital', { metric, reading: 1200, rating: 'good' })).toEqual([]);
    }
    expect(validateEvent('ui.web_vital', { metric: 'fid', reading: 12 }).length).toBeGreaterThan(0);
    expect(validateEvent('ui.web_vital', { metric: 'lcp', reading: 'fast' }).length).toBeGreaterThan(0);
    expect(validateEvent('ui.web_vital', { metric: 'lcp', reading: 1, rating: 'DT4 8XX' }).length).toBeGreaterThan(0);
  });

  it('does not use the keys the collector refuses (name and value)', () => {
    expect(Object.keys(EVENT_SCHEMAS['ui.web_vital'])).toEqual(['metric', 'reading', 'rating']);
  });

  it('is sent by the browser, so its keys are on the attribute list', () => {
    expect(ALLOWED_EVENTS).toContain('ui.web_vital');
    for (const key of ['metric', 'reading', 'rating']) expect(ALLOWED_ATTRIBUTES).toContain(key);
  });
});

describe('track', () => {
  let beacon: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    sessionStorage.clear();
    beacon = vi.fn(() => true);
    Object.defineProperty(navigator, 'sendBeacon', { value: beacon, configurable: true, writable: true });
    initTelemetry({ role: 'advisor', release: '1.4.2' });
  });

  afterEach(() => {
    stopTelemetry();
    vi.unstubAllEnvs();
  });

  it('throws in development on an event that breaks its schema, so the mistake is seen', () => {
    vi.stubEnv('NODE_ENV', 'development');

    expect(() => track('ui.input', { 'element.id': 'ADV-NEEDS-POSTCODE', value: 'DT4 8XX' })).toThrow(/ui\.input/);
  });

  it('drops the event in production and counts the drop', () => {
    vi.stubEnv('NODE_ENV', 'production');
    const before = droppedEvents;

    expect(() => track('ui.input', { 'element.id': 'ADV-NEEDS-POSTCODE', value: 'DT4 8XX' })).not.toThrow();
    flush();

    expect(droppedEvents).toBe(before + 1);
    expect(beacon).not.toHaveBeenCalled();
  });

  it('sends a valid event in production', () => {
    vi.stubEnv('NODE_ENV', 'production');

    track('ui.input', { 'element.id': 'ADV-NEEDS-POSTCODE', valid: true, length_bucket: '6-20' });
    flush();

    expect(beacon).toHaveBeenCalledTimes(1);
  });
});
