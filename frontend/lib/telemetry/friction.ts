// Friction rules (O03): a pure engine. Stub for the red commit: every method does nothing yet.

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

export const QUICK_ACTION_ROUTES: readonly string[] = ['/l/[token]', '/respond/[serviceId]', '/booking/[ref]'];

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
  missed?: { elementId: string; distancePx: number };
};

export type ClickResult = 'navigation' | 'network' | 'dom' | 'state' | 'none';

export type FrictionEngineInit = {
  now: () => number;
  emit: (event: FrictionEvent) => void;
};

export function createFrictionEngine(_init: FrictionEngineInit) {
  return {
    onClick(_click: ClickInput): void {},
    onClickResult(_elementId: string, _result: ClickResult): void {},
    onRequestStart(_elementId: string): void {},
    onRequestEnd(_elementId: string, _status: number): void {},
    onError(_elementId?: string): void {},
    onRoute(_template: string): void {},
    onValidation(_elementId: string, _valid: boolean): void {},
    onFocus(_elementId: string): void {},
    onSubmit(): void {},
    onLeave(): void {},
    onInteraction(): void {},
    onScroll(_direction: 'up' | 'down'): void {},
    onStream(_state: 'open' | 'down'): void {},
    tick(): void {},
  };
}
