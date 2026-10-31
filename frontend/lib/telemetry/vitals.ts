// Web vitals (W9F): the largest contentful paint, the slowest interaction and the layout shift of a
// page, measured with the browser's own PerformanceObserver and handed over once, when the page is
// hidden. Nothing here reads the page's content: an entry has a time, a duration or a score.
//
// The thresholds are the web-vitals "good" and "poor" lines (observability.md, "Performance and
// responsiveness"); the back end keeps its own copy as the budget of each measure.

export type VitalMetric = 'lcp' | 'inp' | 'cls';
export type VitalRating = 'good' | 'needs-improvement' | 'poor';
export type Vital = { metric: VitalMetric; reading: number; rating: VitalRating; route: string | null };

/** [good up to, poor from above]. LCP and INP in milliseconds, CLS as a score. */
export const VITAL_THRESHOLDS: Record<VitalMetric, readonly [number, number]> = {
  lcp: [2500, 4000],
  inp: [200, 500],
  cls: [0.1, 0.25],
};

export function ratingOf(metric: VitalMetric, reading: number): VitalRating {
  const [good, poor] = VITAL_THRESHOLDS[metric];
  if (reading <= good) return 'good';
  return reading <= poor ? 'needs-improvement' : 'poor';
}

type Entry = {
  startTime?: number;
  value?: number;
  hadRecentInput?: boolean;
  duration?: number;
  interactionId?: number;
};

/**
 * Starts watching. `report` is called for each measure when the page is hidden, once: a measure with
 * nothing observed is not reported (a layout shift of none counts once the page has painted).
 * `currentRoute` is the route template now; the paint is filed under the route it was seen on.
 * Returns a function that stops it. In a browser with no PerformanceObserver it does nothing.
 */
export function startVitals(report: (vital: Vital) => void, currentRoute: () => string | null): () => void {
  if (typeof PerformanceObserver === 'undefined' || typeof document === 'undefined') return () => undefined;

  let lcp: { reading: number; route: string | null } | null = null;
  let shifts = 0;
  let slowest: number | null = null;
  const observers: PerformanceObserver[] = [];

  const watch = (type: string, onEntries: (entries: Entry[]) => void, extra: object = {}) => {
    try {
      const observer = new PerformanceObserver((list) => onEntries(list.getEntries() as unknown as Entry[]));
      observer.observe({ type, buffered: true, ...extra } as PerformanceObserverInit);
      observers.push(observer);
    } catch {
      // This browser does not measure this: the others still do.
    }
  };

  watch('largest-contentful-paint', (entries) => {
    const last = entries.at(-1);
    if (last?.startTime !== undefined) lcp = { reading: last.startTime, route: currentRoute() };
  });
  watch('layout-shift', (entries) => {
    for (const entry of entries) {
      if (entry.hadRecentInput !== true && entry.value !== undefined) shifts += entry.value;
    }
  });
  watch(
    'event',
    (entries) => {
      for (const entry of entries) {
        if ((entry.interactionId ?? 0) > 0 && entry.duration !== undefined) {
          slowest = Math.max(slowest ?? 0, entry.duration);
        }
      }
    },
    { durationThreshold: 16 },
  );

  const onVisibility = () => {
    if (document.visibilityState !== 'hidden') return;
    const painted = lcp;
    const shift = shifts;
    const interaction = slowest;
    lcp = null;
    shifts = 0;
    slowest = null;
    if (painted !== null) {
      report({ metric: 'lcp', reading: painted.reading, rating: ratingOf('lcp', painted.reading), route: painted.route });
    }
    if (painted !== null || shift > 0) {
      report({ metric: 'cls', reading: shift, rating: ratingOf('cls', shift), route: currentRoute() });
    }
    if (interaction !== null) {
      report({ metric: 'inp', reading: interaction, rating: ratingOf('inp', interaction), route: currentRoute() });
    }
  };
  document.addEventListener('visibilitychange', onVisibility);

  return () => {
    document.removeEventListener('visibilitychange', onVisibility);
    for (const observer of observers) observer.disconnect();
    observers.length = 0;
  };
}
