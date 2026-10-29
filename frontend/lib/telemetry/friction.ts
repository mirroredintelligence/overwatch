// Friction rules (O03): a pure engine that watches interaction timing and emits one `ui.friction`
// event per rule firing, with the element id it happened on. It never reads content and never ranks a
// person. Time comes from `now()` only; the engine touches no DOM. `attachFriction` is the thin layer
// that wires the engine to the page and to `track`.
//
// The thresholds are starting values [ASSUMED] (docs/spec/observability.md, "Friction signals"). They
// live in one object so that a change is one edit and one review.

import { addRequestObserver } from './trace';
import { track } from './events';

export const FRICTION_THRESHOLDS = {
  rageClicks: 3,
  rageWindowMs: 1000,
  rageDistancePx: 30,
  deadClickMs: 1000,
  errorClickMs: 2000,
  impatientClicks: 2,
  uTurnMs: 5000,
  thrashSwitches: 3,
  thrashWindowMs: 10000,
  validationFailures: 3,
  hesitationMs: 20000,
  missedTapPx: 24,
  scrollReversals: 4,
  scrollWindowMs: 3000,
  streamGapMs: 10000,
} as const;

/** The screens where a person is expected to act at once: hesitation is measured only on these. */
export const QUICK_ACTION_ROUTES: readonly string[] = ['/l/[token]', '/respond/[serviceId]', '/booking/[ref]'];

/** The element id used for friction that belongs to the page or the live stream, not to one control. */
export const FRICTION_EVENT = 'ui.friction' as const;
export const PAGE_ELEMENT_ID = 'PAGE';
export const STREAM_ELEMENT_ID = 'LIVE-STREAM';
/** The element id used for a click that landed on no tagged element. */
export const UNTAGGED_ELEMENT_ID = 'UNTAGGED';

/** How many route changes the engine keeps for the u-turn and thrash rules. */
const ROUTE_TRAIL_LENGTH = 10;

export type FrictionKind =
  | 'rage'
  | 'dead'
  | 'error-click'
  | 'impatient'
  | 'u-turn'
  | 'thrash'
  | 'validation-loop'
  | 'abandonment'
  | 'hesitation'
  | 'missed-tap'
  | 'scroll-thrash'
  | 'stream-gap';

export type FrictionEvent = {
  kind: FrictionKind;
  'element.id': string;
  count: number;
  window_ms: number;
};

export type ClickInput = {
  elementId: string;
  x: number;
  y: number;
  interactive: boolean;
  /** The nearest control the tap did not land on, and how far from the tap it is, in pixels. */
  missed?: { elementId: string; distancePx: number };
};

export type ClickResult = 'navigation' | 'network' | 'dom' | 'state' | 'none';

export type FrictionEngineInit = {
  now: () => number;
  emit: (event: FrictionEvent) => void;
};

type Click = { elementId: string; x: number; y: number; at: number };
type Route = { template: string; at: number; interacted: boolean };

/** Three clicks that count as one burst: each is on the first click's element, or within the distance of the one before. */
function isBurst(group: readonly Click[]): boolean {
  const first = group[0];
  if (first === undefined) return false;
  return group.every((click, index) => {
    if (click.elementId === first.elementId) return true;
    const before = group[index - 1];
    if (before === undefined) return false;
    return Math.hypot(click.x - before.x, click.y - before.y) <= FRICTION_THRESHOLDS.rageDistancePx;
  });
}

export function createFrictionEngine({ now, emit }: FrictionEngineInit) {
  const t = FRICTION_THRESHOLDS;

  let clicks: Click[] = [];
  let pendingDead: { elementId: string; at: number } | null = null;
  let lastClick: { elementId: string; at: number; handled: boolean } | null = null;
  const inFlight = new Map<string, { startedAt: number; clicks: number }>();
  const failures = new Map<string, { count: number; firstAt: number; fired: boolean }>();
  let unsubmitted: { elementId: string; at: number } | null = null;
  let trail: Route[] = [];
  let lastActivity = 0;
  let hesitationFired = false;
  let lastDirection: 'up' | 'down' | null = null;
  let reversals: number[] = [];
  let streamDownSince: number | null = null;
  let streamGapFired = false;

  function fire(kind: FrictionKind, elementId: string, count: number, windowMs: number): void {
    emit({ kind, 'element.id': elementId, count, window_ms: windowMs });
  }

  function markActivity(): void {
    lastActivity = now();
    hesitationFired = false;
  }

  /** Any interaction on the current page: it ends the u-turn window for that page and the idle time. */
  function markInteraction(): void {
    const last = trail[trail.length - 1];
    if (last !== undefined) last.interacted = true;
    markActivity();
  }

  function networkAnswered(elementId: string): void {
    if (pendingDead !== null && pendingDead.elementId === elementId) pendingDead = null;
  }

  function errorAfterClick(): void {
    if (lastClick === null || lastClick.handled) return;
    if (now() - lastClick.at > t.errorClickMs) return;
    lastClick.handled = true;
    fire('error-click', lastClick.elementId, 1, t.errorClickMs);
  }

  return {
    onClick(click: ClickInput): void {
      const at = now();
      markInteraction();

      if (!click.interactive && click.missed !== undefined && click.missed.distancePx <= t.missedTapPx) {
        fire('missed-tap', click.missed.elementId, 1, 0);
      }

      const flight = inFlight.get(click.elementId);
      if (flight !== undefined) {
        flight.clicks += 1;
        fire('impatient', click.elementId, flight.clicks, at - flight.startedAt);
      }

      clicks = clicks.filter((earlier) => at - earlier.at <= t.rageWindowMs);
      clicks.push({ elementId: click.elementId, x: click.x, y: click.y, at });
      if (clicks.length >= t.rageClicks && isBurst(clicks.slice(-t.rageClicks))) {
        fire('rage', click.elementId, clicks.length, t.rageWindowMs);
        clicks = [];
      }

      if (click.interactive) pendingDead = { elementId: click.elementId, at };
      lastClick = { elementId: click.elementId, at, handled: false };
    },

    onClickResult(elementId: string, result: ClickResult): void {
      if (pendingDead === null || pendingDead.elementId !== elementId) return;
      if (result !== 'none') {
        pendingDead = null;
        return;
      }
      if (now() - pendingDead.at >= t.deadClickMs) {
        fire('dead', elementId, 1, t.deadClickMs);
        pendingDead = null;
      }
    },

    /** A network call started from the page answers a click: it is not dead. */
    onNetwork(elementId: string): void {
      networkAnswered(elementId);
    },

    onRequestStart(elementId: string): void {
      inFlight.set(elementId, { startedAt: now(), clicks: 1 });
      networkAnswered(elementId);
    },

    onRequestEnd(elementId: string, status: number): void {
      inFlight.delete(elementId);
      if (status >= 400) errorAfterClick();
    },

    onError(elementId?: string): void {
      // The error is attributed to the click before it, whichever element raised it.
      void elementId;
      errorAfterClick();
    },

    onRoute(template: string): void {
      const at = now();
      const last = trail[trail.length - 1];
      if (last !== undefined && last.template === template) return;
      trail.push({ template, at, interacted: false });
      if (trail.length > ROUTE_TRAIL_LENGTH) trail = trail.slice(-ROUTE_TRAIL_LENGTH);
      markActivity();

      if (trail.length >= 3) {
        const [a, b, c] = trail.slice(-3);
        if (a !== undefined && b !== undefined && c !== undefined) {
          const back = a.template === c.template && a.template !== b.template;
          if (back && !b.interacted && c.at - a.at < t.uTurnMs) fire('u-turn', PAGE_ELEMENT_ID, 1, t.uTurnMs);
        }
      }

      const recent = trail.filter((entry) => entry.at >= at - t.thrashWindowMs);
      const pages = new Set(recent.map((entry) => entry.template));
      const switches = recent.length - 1;
      if (pages.size === 2 && switches >= t.thrashSwitches) {
        fire('thrash', PAGE_ELEMENT_ID, switches, t.thrashWindowMs);
        trail = trail.slice(-1);
      }
    },

    onValidation(elementId: string, valid: boolean): void {
      markInteraction();
      if (valid) {
        failures.delete(elementId);
        return;
      }
      const entry = failures.get(elementId) ?? { count: 0, firstAt: now(), fired: false };
      entry.count += 1;
      failures.set(elementId, entry);
      if (!entry.fired && entry.count >= t.validationFailures) {
        entry.fired = true;
        fire('validation-loop', elementId, entry.count, now() - entry.firstAt);
      }
    },

    onFocus(elementId: string): void {
      markInteraction();
      unsubmitted = { elementId, at: now() };
    },

    onSubmit(): void {
      markInteraction();
      unsubmitted = null;
    },

    onLeave(): void {
      if (unsubmitted === null) return;
      fire('abandonment', unsubmitted.elementId, 1, now() - unsubmitted.at);
      unsubmitted = null;
    },

    onInteraction(): void {
      markInteraction();
    },

    onScroll(direction: 'up' | 'down'): void {
      markInteraction();
      const at = now();
      if (lastDirection !== null && direction !== lastDirection) reversals.push(at);
      lastDirection = direction;
      reversals = reversals.filter((reversal) => at - reversal <= t.scrollWindowMs);
      if (reversals.length >= t.scrollReversals) {
        fire('scroll-thrash', PAGE_ELEMENT_ID, reversals.length, t.scrollWindowMs);
        reversals = [];
      }
    },

    onStream(state: 'open' | 'down'): void {
      const at = now();
      if (state === 'down') {
        if (streamDownSince === null) {
          streamDownSince = at;
          streamGapFired = false;
        }
        return;
      }
      if (streamDownSince !== null && !streamGapFired && at - streamDownSince > t.streamGapMs) {
        fire('stream-gap', STREAM_ELEMENT_ID, 1, at - streamDownSince);
      }
      streamDownSince = null;
      streamGapFired = false;
    },

    /** Checks the rules that depend on time passing: a click with no answer, idle time, a stream that stays down. */
    tick(): void {
      const at = now();
      if (pendingDead !== null && at - pendingDead.at >= t.deadClickMs) {
        fire('dead', pendingDead.elementId, 1, t.deadClickMs);
        pendingDead = null;
      }
      const page = trail[trail.length - 1];
      if (
        page !== undefined &&
        QUICK_ACTION_ROUTES.includes(page.template) &&
        !hesitationFired &&
        at - lastActivity >= t.hesitationMs
      ) {
        hesitationFired = true;
        fire('hesitation', PAGE_ELEMENT_ID, 1, t.hesitationMs);
      }
      if (streamDownSince !== null && !streamGapFired && at - streamDownSince > t.streamGapMs) {
        streamGapFired = true;
        fire('stream-gap', STREAM_ELEMENT_ID, 1, at - streamDownSince);
      }
    },
  };
}

export type FrictionEngine = ReturnType<typeof createFrictionEngine>;

const INTERACTIVE_SELECTOR =
  'button, a[href], input, select, textarea, label, [role="button"], [role="link"], [role="checkbox"], [role="switch"], [aria-pressed]';

export type FrictionHandle = {
  /** Call on every page change with the route template (the caller knows it; the engine does not parse URLs). */
  route(template: string): void;
  /** Call when the live stream opens or drops. */
  stream(state: 'open' | 'down'): void;
  detach(): void;
};

/** The distance from a point to the nearest edge of an element's box: zero when the point is inside it. */
function distanceToBox(x: number, y: number, box: DOMRect): number {
  const dx = Math.max(box.left - x, 0, x - box.right);
  const dy = Math.max(box.top - y, 0, y - box.bottom);
  return Math.hypot(dx, dy);
}

/**
 * Wires the engine to the page and to `track`. Not unit-tested beyond a smoke test. It sees clicks,
 * focus, validation on submit, submit, scroll direction, script errors, DOM changes that answer a click,
 * page leave and BFF requests. It does not see HTTP status codes (the trace hook carries only the trace id),
 * so `error-click` on an HTTP error is not raised by this layer.
 */
export function attachFriction(now: () => number = () => Date.now()): FrictionHandle | null {
  if (typeof window === 'undefined' || typeof document === 'undefined') return null;

  const engine = createFrictionEngine({
    now,
    emit: (event) => track('ui.friction', { ...event }),
  });
  let lastClickElement: string | null = null;
  let lastScrollY = window.scrollY;

  const onClick = (event: MouseEvent): void => {
    const target = event.target instanceof Element ? event.target : null;
    if (target === null) return;
    const tagged = target.closest('[data-el]');
    const elementId = tagged?.getAttribute('data-el') ?? UNTAGGED_ELEMENT_ID;
    const interactive = target.closest(INTERACTIVE_SELECTOR) !== null;
    let missed: ClickInput['missed'];
    if (!interactive) {
      let best: { elementId: string; distancePx: number } | undefined;
      for (const control of Array.from(document.querySelectorAll('[data-el]'))) {
        if (!control.matches(INTERACTIVE_SELECTOR) || control.contains(target)) continue;
        const distancePx = distanceToBox(event.clientX, event.clientY, control.getBoundingClientRect());
        if (best === undefined || distancePx < best.distancePx) {
          best = { elementId: control.getAttribute('data-el') ?? UNTAGGED_ELEMENT_ID, distancePx };
        }
      }
      if (best !== undefined && best.distancePx <= FRICTION_THRESHOLDS.missedTapPx) missed = best;
    }
    lastClickElement = elementId;
    engine.onClick({ elementId, x: event.clientX, y: event.clientY, interactive, missed });
  };
  const onFocusIn = (event: FocusEvent): void => {
    const target = event.target;
    if (target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement || target instanceof HTMLSelectElement) {
      if (target instanceof HTMLInputElement && target.type === 'password') return;
      engine.onFocus(target.getAttribute('data-el') ?? UNTAGGED_ELEMENT_ID);
    }
  };
  const onInput = (): void => engine.onInteraction();
  const onSubmit = (event: Event): void => {
    const form = event.target;
    if (form instanceof HTMLFormElement) {
      for (const field of Array.from(form.querySelectorAll('[data-el]'))) {
        if (field instanceof HTMLInputElement || field instanceof HTMLTextAreaElement || field instanceof HTMLSelectElement) {
          engine.onValidation(field.getAttribute('data-el') ?? UNTAGGED_ELEMENT_ID, field.checkValidity());
        }
      }
    }
    engine.onSubmit();
  };
  const onScroll = (): void => {
    const y = window.scrollY;
    if (y === lastScrollY) return;
    engine.onScroll(y > lastScrollY ? 'down' : 'up');
    lastScrollY = y;
  };
  const onError = (): void => engine.onError();
  const onLeave = (): void => engine.onLeave();
  const onVisibility = (): void => {
    if (document.visibilityState === 'hidden') engine.onLeave();
  };
  const onPopState = (): void => engine.onClickResult(lastClickElement ?? '', 'navigation');

  const observer = new MutationObserver(() => {
    if (lastClickElement !== null) engine.onClickResult(lastClickElement, 'dom');
  });
  observer.observe(document.body, { childList: true, subtree: true, attributes: true, characterData: true });
  const stopRequests = addRequestObserver(() => {
    if (lastClickElement !== null) engine.onNetwork(lastClickElement);
  });
  const timer = setInterval(() => engine.tick(), 1000);

  document.addEventListener('click', onClick, true);
  document.addEventListener('focusin', onFocusIn, true);
  document.addEventListener('input', onInput, true);
  document.addEventListener('submit', onSubmit, true);
  window.addEventListener('scroll', onScroll, { passive: true });
  window.addEventListener('error', onError);
  window.addEventListener('pagehide', onLeave);
  window.addEventListener('popstate', onPopState);
  document.addEventListener('visibilitychange', onVisibility);

  return {
    route(template: string): void {
      engine.onRoute(template);
    },
    stream(state: 'open' | 'down'): void {
      engine.onStream(state);
    },
    detach(): void {
      clearInterval(timer);
      observer.disconnect();
      stopRequests();
      document.removeEventListener('click', onClick, true);
      document.removeEventListener('focusin', onFocusIn, true);
      document.removeEventListener('input', onInput, true);
      document.removeEventListener('submit', onSubmit, true);
      window.removeEventListener('scroll', onScroll);
      window.removeEventListener('error', onError);
      window.removeEventListener('pagehide', onLeave);
      window.removeEventListener('popstate', onPopState);
      document.removeEventListener('visibilitychange', onVisibility);
    },
  };
}
