import { render } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { RELEASE } from '@/lib/release';
import { TelemetryMount } from './TelemetryMount';

const nav = vi.hoisted(() => ({ pathname: '/advisor/case/abc', params: { ref: 'abc' } as Record<string, string> }));
vi.mock('next/navigation', () => ({
  usePathname: () => nav.pathname,
  useParams: () => nav.params,
}));

const events = vi.hoisted(() => ({
  initTelemetry: vi.fn(),
  stopTelemetry: vi.fn(),
  trackPageView: vi.fn(),
  track: vi.fn(),
}));
vi.mock('@/lib/telemetry/events', async (original) => ({
  ...(await original<typeof import('@/lib/telemetry/events')>()),
  ...events,
}));

const friction = vi.hoisted(() => ({ route: vi.fn(), stream: vi.fn(), detach: vi.fn(), attach: vi.fn() }));
vi.mock('@/lib/telemetry/friction', async (original) => ({
  ...(await original<typeof import('@/lib/telemetry/friction')>()),
  attachFriction: friction.attach,
}));

const vitals = vi.hoisted(() => ({ stop: vi.fn(), start: vi.fn() }));
vi.mock('@/lib/telemetry/vitals', async (original) => ({
  ...(await original<typeof import('@/lib/telemetry/vitals')>()),
  startVitals: vitals.start,
}));

beforeEach(() => {
  nav.pathname = '/advisor/case/abc';
  nav.params = { ref: 'abc' };
  for (const fn of [events.initTelemetry, events.stopTelemetry, events.trackPageView, events.track]) fn.mockClear();
  friction.attach.mockReset().mockReturnValue({ route: friction.route, stream: friction.stream, detach: friction.detach });
  friction.route.mockClear();
  friction.detach.mockClear();
  vitals.start.mockReset().mockReturnValue(vitals.stop);
  vitals.stop.mockClear();
});

afterEach(() => vi.restoreAllMocks());

describe('TelemetryMount', () => {
  it('starts the telemetry once with the signed-in role and this build, and renders nothing', () => {
    const { container } = render(<TelemetryMount role="advisor" />);

    expect(events.initTelemetry).toHaveBeenCalledTimes(1);
    expect(events.initTelemetry).toHaveBeenCalledWith({ role: 'advisor', release: RELEASE });
    expect(friction.attach).toHaveBeenCalledTimes(1);
    expect(vitals.start).toHaveBeenCalledTimes(1);
    expect(container).toBeEmptyDOMElement();
  });

  it('records the first screen as a page view of its route template, never the raw path', () => {
    render(<TelemetryMount role="advisor" />);

    expect(events.trackPageView).toHaveBeenCalledTimes(1);
    const view = events.trackPageView.mock.calls[0]?.[0] as { route: string; from?: string; loadType: string };
    expect(view.route).toBe('/advisor/case/[ref]');
    expect(view.from).toBeUndefined();
    expect(['navigate', 'reload', 'back_forward']).toContain(view.loadType);
    expect(JSON.stringify(events.trackPageView.mock.calls)).not.toContain('abc');
    expect(friction.route).toHaveBeenCalledWith('/advisor/case/[ref]');
  });

  it('records the next screen with the one it came from', () => {
    const { rerender } = render(<TelemetryMount role="advisor" />);

    nav.pathname = '/advisor/case/abc/options';
    rerender(<TelemetryMount role="advisor" />);

    expect(events.trackPageView).toHaveBeenCalledTimes(2);
    expect(events.trackPageView.mock.calls[1]?.[0]).toEqual({
      route: '/advisor/case/[ref]/options',
      from: '/advisor/case/[ref]',
      loadType: 'navigate',
    });
    expect(events.initTelemetry).toHaveBeenCalledTimes(1);
  });

  it('does not record a page view again for a re-render on the same screen', () => {
    const { rerender } = render(<TelemetryMount role="advisor" />);

    rerender(<TelemetryMount role="advisor" />);

    expect(events.trackPageView).toHaveBeenCalledTimes(1);
  });

  it('sends a web vital as a ui.web_vital event with its metric, reading and rating, on its route', () => {
    render(<TelemetryMount role="advisor" />);
    const report = vitals.start.mock.calls[0]?.[0] as (vital: object) => void;

    report({ metric: 'lcp', reading: 2400, rating: 'good', route: '/advisor/board' });
    report({ metric: 'cls', reading: 0.02, rating: 'good', route: null });

    expect(events.track).toHaveBeenNthCalledWith(1, 'ui.web_vital', {
      metric: 'lcp',
      reading: 2400,
      rating: 'good',
      'page.route': '/advisor/board',
    });
    expect(events.track).toHaveBeenNthCalledWith(2, 'ui.web_vital', { metric: 'cls', reading: 0.02, rating: 'good' });
  });

  it('stops everything it started when it goes away', () => {
    const { unmount } = render(<TelemetryMount role="advisor" />);

    unmount();

    expect(friction.detach).toHaveBeenCalledTimes(1);
    expect(vitals.stop).toHaveBeenCalledTimes(1);
    expect(events.stopTelemetry).toHaveBeenCalledTimes(1);
  });
});
