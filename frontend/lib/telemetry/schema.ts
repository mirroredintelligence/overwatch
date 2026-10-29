// Telemetry schema (O05). Every attribute the browser sends is a number, a boolean, a fixed enum or an
// id that matches a fixed pattern. A plain string with no enum and no pattern is free text, and free
// text is not allowed in telemetry: it is how a typed value, a name or a postcode would leave the
// browser. `track` checks each event here before it queues it.

export type AttrSpec =
  | { type: 'number' }
  | { type: 'boolean' }
  | { type: 'enum'; values: string[] }
  | { type: 'id'; pattern: RegExp };

export const UI_EVENT_NAMES = [
  'ui.page_view',
  'ui.click',
  'ui.input',
  'ui.toggle',
  'ui.chip',
  'ui.submit',
  'ui.error_shown',
  'ui.friction',
] as const;

export type UiEventName = (typeof UI_EVENT_NAMES)[number];

/** The roles, as lib/auth/session.ts defines them. A test keeps the two lists equal. */
export const ROLE_VALUES: readonly string[] = [
  'reporter',
  'advisor',
  'clinical',
  'lead',
  'owner',
  'exec',
  'wall',
  'anonymous-link',
  'support',
  'audit',
];

const ELEMENT_ID = /^[A-Z0-9]+(-[A-Z0-9]+)*$/;
const ROUTE_TEMPLATE = /^\/[a-z0-9\-/[\]]*$/;
const SESSION_ID = /^[a-f0-9]{16,32}$/;
const TRACE_ID = /^[a-f0-9]{32}$/;
const RELEASE = /^\d+\.\d+\.\d+$/;
const ERROR_CODE = /^[A-Z0-9_-]{1,40}$/;
const SERVICE_ID = /^[A-Za-z0-9-]{1,64}$/;

/** Attributes any event may carry (added by `track` from the session and the page). */
export const COMMON_SCHEMA: Record<string, AttrSpec> = {
  'session.id': { type: 'id', pattern: SESSION_ID },
  'user.role': { type: 'enum', values: [...ROLE_VALUES] },
  release: { type: 'id', pattern: RELEASE },
  'device.type': { type: 'enum', values: ['phone', 'tablet', 'desktop'] },
  'app.mode': { type: 'enum', values: ['browser', 'installed'] },
  'net.effective_type': { type: 'enum', values: ['slow-2g', '2g', '3g', '4g'] },
  'page.route': { type: 'id', pattern: ROUTE_TEMPLATE },
  trace_id: { type: 'id', pattern: TRACE_ID },
  'service.id': { type: 'id', pattern: SERVICE_ID },
};

const FRICTION_KINDS = [
  'rage',
  'dead',
  'error-click',
  'impatient',
  'u-turn',
  'thrash',
  'validation-loop',
  'abandonment',
  'hesitation',
  'missed-tap',
  'scroll-thrash',
  'stream-gap',
];

export const EVENT_SCHEMAS: Record<UiEventName, Record<string, AttrSpec>> = {
  'ui.page_view': {
    'from.route': { type: 'id', pattern: ROUTE_TEMPLATE },
    'load.type': { type: 'enum', values: ['navigate', 'reload', 'back_forward'] },
  },
  'ui.click': {
    'element.id': { type: 'id', pattern: ELEMENT_ID },
    dwell_ms: { type: 'number' },
    result: { type: 'enum', values: ['navigation', 'network', 'dom', 'none'] },
  },
  'ui.input': {
    'element.id': { type: 'id', pattern: ELEMENT_ID },
    valid: { type: 'boolean' },
    length_bucket: { type: 'enum', values: ['0', '1-5', '6-20', '21+'] },
  },
  'ui.toggle': {
    'element.id': { type: 'id', pattern: ELEMENT_ID },
    state: { type: 'enum', values: ['on', 'off'] },
  },
  'ui.chip': {
    'element.id': { type: 'id', pattern: ELEMENT_ID },
    state: { type: 'enum', values: ['true', 'false'] },
  },
  'ui.submit': {
    'form.id': { type: 'id', pattern: ELEMENT_ID },
    error_count: { type: 'number' },
    time_to_submit_ms: { type: 'number' },
  },
  'ui.error_shown': {
    'error.code': { type: 'id', pattern: ERROR_CODE },
    'element.id': { type: 'id', pattern: ELEMENT_ID },
  },
  'ui.friction': {
    kind: { type: 'enum', values: FRICTION_KINDS },
    'element.id': { type: 'id', pattern: ELEMENT_ID },
    count: { type: 'number' },
    window_ms: { type: 'number' },
  },
};

// Values that a person could type into a field, or that a patient record could hold. A pattern that
// accepts any of them would let free text through, so isFreeText rejects it.
const FREE_TEXT_PROBES = ['Sample Patient', 'DT4 8XX', 'A B', 'x@example.com', 'Dr Jones'];

// A fixed code: letters, digits and a few separators, never a sentence.
const ENUM_CODE = /^[A-Za-z0-9][A-Za-z0-9_.+\-/[\]]*$/;
const ENUM_MAX_LENGTH = 40;

/**
 * True when a spec could hold free text. This is a check of the spec's shape and of a few probe
 * values, not of what a real event carries: an id pattern must be anchored and must reject every
 * probe; an enum must list only short fixed codes. A number or a boolean cannot hold text.
 */
export function isFreeText(spec: AttrSpec): boolean {
  switch (spec.type) {
    case 'number':
    case 'boolean':
      return false;
    case 'enum':
      return (
        spec.values.length === 0 ||
        spec.values.some((value) => value.length > ENUM_MAX_LENGTH || !ENUM_CODE.test(value))
      );
    case 'id': {
      const source = spec.pattern.source;
      if (!source.startsWith('^') || !source.endsWith('$')) return true;
      return FREE_TEXT_PROBES.some((probe) => spec.pattern.test(probe));
    }
  }
}

function isUiEventName(name: string): name is UiEventName {
  return (UI_EVENT_NAMES as readonly string[]).includes(name);
}

function allows(spec: AttrSpec, value: unknown): boolean {
  switch (spec.type) {
    case 'number':
      return typeof value === 'number' && Number.isFinite(value);
    case 'boolean':
      return typeof value === 'boolean';
    case 'enum':
      return typeof value === 'string' && spec.values.includes(value);
    case 'id':
      return typeof value === 'string' && spec.pattern.test(value);
  }
}

/**
 * The problems with an event's attributes, one line each. An empty list means the event may be sent.
 * A problem names the attribute and never repeats its value, so the message cannot carry what it refused.
 */
export function validateEvent(name: string, attributes: Record<string, unknown>): string[] {
  if (!isUiEventName(name)) return [`unknown event ${name}`];
  const schema: Record<string, AttrSpec> = { ...COMMON_SCHEMA, ...EVENT_SCHEMAS[name] };
  const problems: string[] = [];
  for (const [key, value] of Object.entries(attributes)) {
    const spec = schema[key];
    if (spec === undefined) {
      problems.push(`${key} is not an attribute of ${name}`);
    } else if (!allows(spec, value)) {
      problems.push(`${key} does not match its schema for ${name}`);
    }
  }
  return problems;
}
