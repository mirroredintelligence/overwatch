import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ratingOf, startVitals, type Vital } from './vitals';

// A stand-in for PerformanceObserver that lets a test deliver entries of one type.
type Callback = (list: { getEntries: () => PerformanceEntry[] }) => void;
let observers: Array<{ type: string; callback: Callback; disconnected: boolean }>;

class FakeObserver {
  private readonly callback: Callback;
  private entry: { type: string; callback: Callback; disconnected: boolean } | null = null;
  constructor(callback: Callback) {
    this.callback = callback;
  }
  observe(options: { type: string }) {
    if (options.type === 'unsupported') throw new TypeError('unsupported entry type');
    this.entry = { type: options.type, callback: this.callback, disconnected: false };
    observers.push(this.entry);
  }
  disconnect() {
    if (this.entry) this.entry.disconnected = true;
  }
}

function deliver(type: string, entries: object[]) {
  for (const observer of observers.filter((item) => item.type === type && !item.disconnected)) {
    observer.callback({ getEntries: () => entries as PerformanceEntry[] });
  }
}

function hide() {
  Object.defineProperty(document, 'visibilityState', { value: 'hidden', configurable: true });
  document.dispatchEvent(new Event('visibilitychange'));
}

let reported: Vital[];
let stop: () => void;
let route: string | null;

beforeEach(() => {
  observers = [];
  reported = [];
  route = '/advisor/board';
  vi.stubGlobal('PerformanceObserver', FakeObserver);
  stop = startVitals((vital) => reported.push(vital), () => route);
});

afterEach(() => {
  stop();
  vi.unstubAllGlobals();
  Object.defineProperty(document, 'visibilityState', { value: 'visible', configurable: true });
});

describe('ratingOf', () => {
  it('is good up to the web-vitals threshold, then needs improvement, then poor', () => {
    expect(ratingOf('lcp', 2500)).toBe('good');
    expect(ratingOf('lcp', 2501)).toBe('needs-improvement');
    expect(ratingOf('lcp', 4000)).toBe('needs-improvement');
    expect(ratingOf('lcp', 4001)).toBe('poor');
    expect(ratingOf('inp', 200)).toBe('good');
    expect(ratingOf('inp', 500)).toBe('needs-improvement');
    expect(ratingOf('inp', 501)).toBe('poor');
    expect(ratingOf('cls', 0.1)).toBe('good');
    expect(ratingOf('cls', 0.25)).toBe('needs-improvement');
    expect(ratingOf('cls', 0.26)).toBe('poor');
  });
});

describe('startVitals', () => {
  it('reports the last largest contentful paint when the page is hidden, and not before', () => {
    deliver('largest-contentful-paint', [{ startTime: 1200 }, { startTime: 2400 }]);
    expect(reported).toEqual([]);

    hide();

    expect(reported).toContainEqual({ metric: 'lcp', reading: 2400, rating: 'good', route: '/advisor/board' });
  });

  it('attributes the paint to the route it was seen on, not the one the person left from', () => {
    deliver('largest-contentful-paint', [{ startTime: 900 }]);
    route = '/advisor/case/[ref]';

    hide();

    expect(reported.find((vital) => vital.metric === 'lcp')?.route).toBe('/advisor/board');
  });

  it('adds up layout shifts that were not caused by input', () => {
    deliver('layout-shift', [
      { value: 0.05, hadRecentInput: false },
      { value: 0.5, hadRecentInput: true },
      { value: 0.07, hadRecentInput: false },
    ]);

    hide();

    const cls = reported.find((vital) => vital.metric === 'cls');
    expect(cls?.reading).toBeCloseTo(0.12, 5);
    expect(cls?.rating).toBe('needs-improvement');
  });

  it('reports no layout shift as zero once the page has painted', () => {
    deliver('largest-contentful-paint', [{ startTime: 800 }]);

    hide();

    expect(reported.find((vital) => vital.metric === 'cls')).toMatchObject({ reading: 0, rating: 'good' });
  });

  it('reports the slowest interaction, counting only entries that belong to an interaction', () => {
    deliver('event', [
      { duration: 80, interactionId: 1 },
      { duration: 240, interactionId: 2 },
      { duration: 900, interactionId: 0 },
    ]);

    hide();

    expect(reported.find((vital) => vital.metric === 'inp')).toMatchObject({ reading: 240, rating: 'needs-improvement' });
  });

  it('reports no interaction measure when nothing was interacted with', () => {
    deliver('largest-contentful-paint', [{ startTime: 800 }]);

    hide();

    expect(reported.map((vital) => vital.metric)).not.toContain('inp');
  });

  it('reports each measure once per time the page is hidden, then starts again', () => {
    deliver('largest-contentful-paint', [{ startTime: 800 }]);
    hide();
    hide();
    expect(reported.filter((vital) => vital.metric === 'lcp')).toHaveLength(1);

    deliver('event', [{ duration: 120, interactionId: 3 }]);
    hide();

    expect(reported.filter((vital) => vital.metric === 'inp')).toHaveLength(1);
  });

  it('reports nothing when the page is only shown again', () => {
    deliver('largest-contentful-paint', [{ startTime: 800 }]);
    Object.defineProperty(document, 'visibilityState', { value: 'visible', configurable: true });

    document.dispatchEvent(new Event('visibilitychange'));

    expect(reported).toEqual([]);
  });

  it('stops watching: no observer is left and nothing is reported afterwards', () => {
    deliver('largest-contentful-paint', [{ startTime: 800 }]);

    stop();
    hide();

    expect(observers.every((observer) => observer.disconnected)).toBe(true);
    expect(reported).toEqual([]);
  });

  it('does nothing, and does not throw, in a browser with no performance observer', () => {
    stop();
    vi.stubGlobal('PerformanceObserver', undefined);
    const quiet: Vital[] = [];

    const off = startVitals((vital) => quiet.push(vital), () => null);
    hide();
    off();

    expect(quiet).toEqual([]);
  });

  it('carries on when one entry type is not supported', () => {
    stop();
    observers = [];
    vi.stubGlobal(
      'PerformanceObserver',
      class extends FakeObserver {
        override observe(options: { type: string }) {
          super.observe(options.type === 'event' ? { type: 'unsupported' } : options);
        }
      },
    );
    const seen: Vital[] = [];
    const off = startVitals((vital) => seen.push(vital), () => '/x');

    deliver('largest-contentful-paint', [{ startTime: 700 }]);
    hide();
    off();

    expect(seen.map((vital) => vital.metric)).toContain('lcp');
  });
});
