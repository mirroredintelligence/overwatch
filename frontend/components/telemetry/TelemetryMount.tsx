'use client';

import { useParams, usePathname } from 'next/navigation';
import { useEffect, useRef } from 'react';
import { RELEASE } from '@/lib/release';
import { initTelemetry, routeTemplate, stopTelemetry, track, trackPageView } from '@/lib/telemetry/events';
import { attachFriction, type FrictionHandle } from '@/lib/telemetry/friction';
import { startVitals } from '@/lib/telemetry/vitals';

// Starts the browser's telemetry for a signed-in person (O02, O03, W9F): the ui.* events, the friction
// rules and the web vitals, and records each screen as a page view of its route template (never the raw
// path). Renders nothing. Mounted once, in the root layout, for a person who has a session: the ingest
// answers 401 without one.

function loadType(): 'navigate' | 'reload' | 'back_forward' {
  const entry = typeof performance.getEntriesByType === 'function' ? performance.getEntriesByType('navigation')[0] : undefined;
  const type = (entry as PerformanceNavigationTiming | undefined)?.type;
  return type === 'reload' || type === 'back_forward' ? type : 'navigate';
}

export function TelemetryMount({ role }: { role: string }) {
  const pathname = usePathname();
  const params = useParams();
  const friction = useRef<FrictionHandle | null>(null);
  const route = useRef<string | null>(null);
  const first = useRef(true);

  useEffect(() => {
    initTelemetry({ role, release: RELEASE });
    friction.current = attachFriction();
    const stopVitals = startVitals(
      (vital) =>
        track('ui.web_vital', {
          metric: vital.metric,
          reading: vital.reading,
          rating: vital.rating,
          ...(vital.route === null ? {} : { 'page.route': vital.route }),
        }),
      () => route.current,
    );
    return () => {
      friction.current?.detach();
      friction.current = null;
      stopVitals();
      stopTelemetry();
      first.current = true;
      route.current = null;
    };
  }, [role]);

  useEffect(() => {
    const template = routeTemplate(pathname, (params ?? {}) as Record<string, string>);
    if (template === route.current) return;
    const from = route.current;
    route.current = template;
    trackPageView({ route: template, ...(from === null ? {} : { from }), loadType: first.current ? loadType() : 'navigate' });
    first.current = false;
    friction.current?.route(template);
  }, [pathname, params]);

  return null;
}
