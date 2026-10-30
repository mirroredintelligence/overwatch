// Browser telemetry (O02): the ui.* events, tied to stable element ids. It records which element was
// used and what happened next, never what was typed. No field value, page text, screenshot or DOM is
// captured, and a password field is not measured at all. Events are batched and sent with
// navigator.sendBeacon to /api/bff/telemetry, which keeps only the attributes on ALLOWED_ATTRIBUTES.
//
// Nothing here runs on the server: every entry point touches window or document when it is called.

import { beginInteraction, currentTraceId, setRequestObserver } from './trace';
import { UI_EVENT_NAMES, validateEvent } from './schema';

export const TELEMETRY_ENDPOINT = '/api/bff/telemetry';
export const BATCH_SIZE = 20;
export const FLUSH_MS = 5000;
/** How long a click waits for a visible result before it is recorded as `none`. */
export const CLICK_WINDOW_MS = 1000;

const SESSION_KEY = 'diucs.session.id';

/** The events this module sends (the names are fixed in schema.ts). Anything else is refused by the BFF route. */
export const ALLOWED_EVENTS: readonly string[] = UI_EVENT_NAMES;

/** The attribute keys the browser sends. The BFF route adds tenant.id from the session itself. */
export const ALLOWED_ATTRIBUTES: readonly string[] = [
  // Common to every event.
  'session.id',
  'user.role',
  'service.id',
  'page.route',
  'element.id',
  'release',
  'device.type',
  'app.mode',
  'net.effective_type',
  'trace_id',
  // Per event.
  'from.route',
  'load.type',
  'dwell_ms',
  'result',
  'valid',
  'length_bucket',
  'state',
  'form.id',
  'error_count',
  'time_to_submit_ms',
  'error.code',
  // ui.friction (O03).
  'kind',
  'count',
  'window_ms',
];

export type Attributes = Record<string, string | number | boolean>;
export type TelemetryInit = { role: string; release: string };

type QueuedEvent = { name: string; at: number; attributes: Attributes };
type PendingClick = { elementId: string; dwellMs: number; timer: ReturnType<typeof setTimeout> };

type State = {
  role: string;
  release: string;
  sessionId: string;
  currentRoute: string | null;
  queue: QueuedEvent[];
  timer: ReturnType<typeof setInterval>;
  pending: PendingClick | null;
  hoverStart: WeakMap<Element, number>;
  formStart: WeakMap<Element, number>;
  observer: MutationObserver;
  listeners: Array<[EventTarget, string, EventListener, boolean]>;
  originalPushState: History['pushState'];
  originalReplaceState: History['replaceState'];
};

let state: State | null = null;

/** Events dropped because they broke their schema (O05). Read it in a test or a dashboard, never sent. */
export let droppedEvents = 0;

function randomHex(bytes: number): string {
  const buffer = new Uint8Array(bytes);
  crypto.getRandomValues(buffer);
  return Array.from(buffer, (byte) => byte.toString(16).padStart(2, '0')).join('');
}

/** The session id: random per browser session, kept in sessionStorage. Not linked to a person here. */
function sessionIdentifier(): string {
  try {
    const stored = sessionStorage.getItem(SESSION_KEY);
    if (stored && /^[a-f0-9]{16,32}$/.test(stored)) return stored;
    const fresh = randomHex(16);
    sessionStorage.setItem(SESSION_KEY, fresh);
    return fresh;
  } catch {
    // sessionStorage can be blocked. The id then lasts for this page only.
    return randomHex(16);
  }
}

function deviceType(): 'phone' | 'tablet' | 'desktop' {
  const width = window.innerWidth;
  if (width < 600) return 'phone';
  if (width < 1024) return 'tablet';
  return 'desktop';
}

function appMode(): 'browser' | 'installed' {
  return window.matchMedia?.('(display-mode: standalone)').matches ? 'installed' : 'browser';
}

const NETWORK_TYPES: readonly string[] = ['slow-2g', '2g', '3g', '4g'];

/** The connection type, only when it is one the schema names (anything else is left out, not sent). */
function effectiveType(): string | undefined {
  const connection = (navigator as Navigator & { connection?: { effectiveType?: unknown } }).connection;
  const value = connection?.effectiveType;
  return typeof value === 'string' && NETWORK_TYPES.includes(value) ? value : undefined;
}

function commonAttributes(current: State): Attributes {
  const attributes: Attributes = {
    'session.id': current.sessionId,
    'user.role': current.role,
    release: current.release,
    'device.type': deviceType(),
    'app.mode': appMode(),
  };
  const network = effectiveType();
  if (network !== undefined) attributes['net.effective_type'] = network;
  if (current.currentRoute !== null) attributes['page.route'] = current.currentRoute;
  const traceId = currentTraceId();
  if (traceId !== null) attributes.trace_id = traceId;
  return attributes;
}

/** The length of a typed value, in buckets. The value itself is never read into an event. */
export function lengthBucket(length: number): '0' | '1-5' | '6-20' | '21+' {
  if (length === 0) return '0';
  if (length <= 5) return '1-5';
  if (length <= 20) return '6-20';
  return '21+';
}

/** A route template for a pathname: each parameter value becomes its name in brackets. */
export function routeTemplate(pathname: string, params: Record<string, string>): string {
  const entries = Object.entries(params).filter(([, value]) => value !== '');
  return pathname
    .split('/')
    .map((segment) => {
      const match = entries.find(([, value]) => segment === value || safeDecode(segment) === value);
      return match ? `[${match[0]}]` : segment;
    })
    .join('/');
}

function safeDecode(segment: string): string {
  try {
    return decodeURIComponent(segment);
  } catch {
    return segment;
  }
}

/** Only the attributes on the allow-list are queued. */
function allowed(attributes: Attributes): Attributes {
  const kept: Attributes = {};
  for (const [key, value] of Object.entries(attributes)) {
    if (ALLOWED_ATTRIBUTES.includes(key)) kept[key] = value;
  }
  return kept;
}

/**
 * Queues one ui.* event after its schema check. An event that breaks its schema is refused: in
 * development `track` throws, so the mistake is seen; elsewhere it is dropped and counted in
 * droppedEvents. The error names the event and the attributes, never their values.
 */
export function track(name: string, attributes: Attributes = {}): void {
  if (state === null) return;
  const current = state;
  const merged: Attributes = { ...commonAttributes(current), ...attributes };
  const problems = validateEvent(name, merged);
  if (problems.length > 0) {
    if (process.env.NODE_ENV === 'development') {
      throw new Error(`telemetry: ${name} breaks its schema: ${problems.join('; ')}`);
    }
    droppedEvents += 1;
    return;
  }
  current.queue.push({ name, at: Date.now(), attributes: allowed(merged) });
  if (current.queue.length >= BATCH_SIZE) flush();
}

/**
 * Sends everything queued now. The body is text: a beacon that is text/plain needs no CORS preflight,
 * and the BFF route reads it as JSON whatever its content type. Falls back to a keep-alive fetch when
 * the browser refuses the beacon.
 */
export function flush(): void {
  if (state === null || state.queue.length === 0) return;
  const events = state.queue.splice(0, state.queue.length);
  const body = JSON.stringify({ events });
  const queued = typeof navigator.sendBeacon === 'function' && navigator.sendBeacon(TELEMETRY_ENDPOINT, body);
  if (!queued) {
    void fetch(TELEMETRY_ENDPOINT, {
      method: 'POST',
      body,
      headers: { 'Content-Type': 'text/plain;charset=UTF-8' },
      keepalive: true,
      credentials: 'same-origin',
    }).catch(() => undefined);
  }
}

export function trackPageView(view: { route: string; from?: string; loadType: string }): void {
  if (state !== null) state.currentRoute = view.route;
  track('ui.page_view', {
    'page.route': view.route,
    ...(view.from === undefined ? {} : { 'from.route': view.from }),
    'load.type': view.loadType,
  });
}

function finishClick(result: 'navigation' | 'network' | 'dom' | 'none'): void {
  const current = state;
  if (current === null || current.pending === null) return;
  const { elementId, dwellMs, timer } = current.pending;
  clearTimeout(timer);
  current.pending = null;
  track('ui.click', { 'element.id': elementId, dwell_ms: dwellMs, result });
}

/** A visible result of the click in progress: the first one wins, and the click is recorded at once. */
function signalResult(result: 'navigation' | 'network' | 'dom'): void {
  finishClick(result);
}

function startClick(element: Element, elementId: string): void {
  const current = state;
  if (current === null) return;
  finishClick('none');
  // Changes made before this click (queued, not yet delivered) are not a result of it.
  current.observer.takeRecords();
  const started = Date.now();
  const hoveredAt = current.hoverStart.get(element) ?? started;
  current.pending = {
    elementId,
    dwellMs: Math.max(0, started - hoveredAt),
    timer: setTimeout(() => finishClick('none'), CLICK_WINDOW_MS),
  };
  beginInteraction();
  if (element.hasAttribute('aria-pressed')) {
    // A chip or a switch: its state after the click, read once the handlers have run.
    const pressed = element.getAttribute('aria-pressed') ?? 'false';
    queueMicrotask(() => track('ui.chip', { 'element.id': elementId, state: pressed }));
  }
}

function elementAt(target: EventTarget | null): { element: Element; id: string } | null {
  if (!(target instanceof Element)) return null;
  const element = target.closest('[data-el]');
  if (element === null) return null;
  return { element, id: element.getAttribute('data-el') ?? '' };
}

function onClick(event: Event): void {
  const found = elementAt(event.target);
  if (found === null || found.id === '') return;
  startClick(found.element, found.id);
}

function onPointerOver(event: Event): void {
  const found = elementAt(event.target);
  if (found === null || state === null) return;
  state.hoverStart.set(found.element, Date.now());
}

function onInput(event: Event): void {
  const target = event.target;
  if (!(target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement)) return;
  // A password is not measured, not even its length.
  if (target instanceof HTMLInputElement && target.type === 'password') return;
  const found = elementAt(target);
  if (found === null || found.id === '') return;
  track('ui.input', {
    'element.id': found.id,
    valid: target.checkValidity(),
    length_bucket: lengthBucket(target.value.length),
  });
}

function onChange(event: Event): void {
  const target = event.target;
  if (!(target instanceof HTMLInputElement) || (target.type !== 'checkbox' && target.type !== 'radio')) return;
  const found = elementAt(target);
  if (found === null || found.id === '') return;
  track('ui.toggle', { 'element.id': found.id, state: target.checked ? 'on' : 'off' });
}

function onFocusIn(event: Event): void {
  const form = event.target instanceof Element ? event.target.closest('form') : null;
  if (form !== null && state !== null && !state.formStart.has(form)) {
    state.formStart.set(form, Date.now());
  }
}

function onSubmit(event: Event): void {
  const form = event.target;
  if (!(form instanceof HTMLFormElement) || state === null) return;
  const started = state.formStart.get(form) ?? Date.now();
  state.formStart.delete(form);
  track('ui.submit', {
    'form.id': form.getAttribute('data-el') ?? 'FORM-UNNAMED',
    error_count: form.querySelectorAll('[aria-invalid="true"]').length,
    time_to_submit_ms: Math.max(0, Date.now() - started),
  });
}

function onMutations(records: MutationRecord[]): void {
  if (state === null) return;
  if (state.pending !== null && records.length > 0) signalResult('dom');
  for (const record of records) {
    for (const node of Array.from(record.addedNodes)) {
      if (!(node instanceof HTMLElement) || node.getAttribute('role') !== 'alert') continue;
      track('ui.error_shown', {
        'error.code': node.getAttribute('data-error-code') ?? 'UNSPECIFIED',
        ...(node.getAttribute('data-el') ? { 'element.id': node.getAttribute('data-el') ?? '' } : {}),
      });
    }
  }
}

export function noteRouteChange(): void {
  signalResult('navigation');
}

function listen(target: EventTarget, type: string, listener: EventListener, capture = false): void {
  target.addEventListener(type, listener, capture);
  state?.listeners.push([target, type, listener, capture]);
}

/** Starts the telemetry for this page. Safe to call twice: the second call does nothing. */
export function initTelemetry(init: TelemetryInit): void {
  if (state !== null || typeof window === 'undefined') return;
  const originalPushState = history.pushState.bind(history);
  const originalReplaceState = history.replaceState.bind(history);
  const observer = new MutationObserver(onMutations);
  state = {
    role: init.role,
    release: init.release,
    sessionId: sessionIdentifier(),
    currentRoute: null,
    queue: [],
    timer: setInterval(flush, FLUSH_MS),
    pending: null,
    hoverStart: new WeakMap(),
    formStart: new WeakMap(),
    observer,
    listeners: [],
    originalPushState: history.pushState,
    originalReplaceState: history.replaceState,
  };
  observer.observe(document.body, { childList: true, subtree: true, attributes: true, characterData: true });
  history.pushState = (...args: Parameters<History['pushState']>) => {
    originalPushState(...args);
    noteRouteChange();
  };
  history.replaceState = (...args: Parameters<History['replaceState']>) => {
    originalReplaceState(...args);
    noteRouteChange();
  };
  setRequestObserver(() => signalResult('network'));
  listen(document, 'click', onClick, true);
  listen(document, 'pointerover', onPointerOver, true);
  listen(document, 'input', onInput, true);
  listen(document, 'change', onChange, true);
  listen(document, 'focusin', onFocusIn, true);
  listen(document, 'submit', onSubmit, true);
  listen(window, 'popstate', noteRouteChange);
  listen(document, 'visibilitychange', () => {
    if (document.visibilityState === 'hidden') flush();
  });
  listen(window, 'pagehide', flush);
}

/** Stops the telemetry and drops what is queued. Used when a page goes away, and by the tests. */
export function stopTelemetry(): void {
  const current = state;
  if (current === null) return;
  clearInterval(current.timer);
  if (current.pending !== null) clearTimeout(current.pending.timer);
  current.observer.disconnect();
  for (const [target, type, listener, capture] of current.listeners) {
    target.removeEventListener(type, listener, capture);
  }
  history.pushState = current.originalPushState;
  history.replaceState = current.originalReplaceState;
  setRequestObserver(null);
  state = null;
}
