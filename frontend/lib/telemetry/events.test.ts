import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { withTraceparent } from './trace';
import {
  BATCH_SIZE,
  FLUSH_MS,
  flush,
  initTelemetry,
  routeTemplate,
  stopTelemetry,
  track,
  trackPageView,
} from './events';

type SentEvent = { name: string; attributes: Record<string, unknown> };

let beacon: ReturnType<typeof vi.fn>;

// Lets the MutationObserver and the other microtasks run under fake timers.
async function settle(): Promise<void> {
  for (let i = 0; i < 5; i += 1) await Promise.resolve();
}

// Sends what is queued and returns every event the beacons carried, in order.
async function sentEvents(): Promise<SentEvent[]> {
  flush();
  await settle();
  const events: SentEvent[] = [];
  for (const [, body] of beacon.mock.calls) {
    const parsed = JSON.parse(await (body as Blob).text()) as { events: SentEvent[] };
    events.push(...parsed.events);
  }
  beacon.mockClear();
  return events;
}

function button(el: string): HTMLButtonElement {
  const node = document.createElement('button');
  node.dataset.el = el;
  node.textContent = 'Request';
  document.body.append(node);
  return node;
}

beforeEach(() => {
  vi.useFakeTimers();
  sessionStorage.clear();
  document.body.innerHTML = '';
  beacon = vi.fn(() => true);
  Object.defineProperty(navigator, 'sendBeacon', { value: beacon, configurable: true, writable: true });
  initTelemetry({ role: 'advisor', release: 'test-release-1' });
});

afterEach(() => {
  stopTelemetry();
  vi.useRealTimers();
});

describe('routeTemplate', () => {
  it('replaces each parameter value with its name in brackets', () => {
    expect(routeTemplate('/case/4821/options', { ref: '4821' })).toBe('/case/[ref]/options');
  });

  it('leaves a path with no parameter values as it is', () => {
    expect(routeTemplate('/board', {})).toBe('/board');
  });
});

describe('ui.click', () => {
  it('records result dom when the page changes within a second of the click', async () => {
    const request = button('ADV-OPT-REQUEST-BTN');
    request.addEventListener('click', () => {
      document.body.append(document.createElement('p'));
    });

    request.click();
    await settle();
    const events = await sentEvents();

    const click = events.find((event) => event.name === 'ui.click');
    expect(click?.attributes['element.id']).toBe('ADV-OPT-REQUEST-BTN');
    expect(click?.attributes.result).toBe('dom');
  });

  it('records result none when nothing happens for a second', async () => {
    const request = button('ADV-OPT-REQUEST-BTN');

    request.click();
    await vi.advanceTimersByTimeAsync(1000);
    const events = await sentEvents();

    expect(events.find((event) => event.name === 'ui.click')?.attributes.result).toBe('none');
  });

  it('records result network when a BFF request starts within a second', async () => {
    const request = button('ADV-OPT-REQUEST-BTN');
    request.addEventListener('click', () => {
      withTraceparent({ method: 'GET' });
    });

    request.click();
    await settle();
    const events = await sentEvents();

    expect(events.find((event) => event.name === 'ui.click')?.attributes.result).toBe('network');
  });

  it('records result navigation when the route changes within a second', async () => {
    const request = button('ADV-OPT-REQUEST-BTN');
    request.addEventListener('click', () => {
      history.pushState({}, '', '/case/4821');
    });

    request.click();
    await settle();
    const events = await sentEvents();

    expect(events.find((event) => event.name === 'ui.click')?.attributes.result).toBe('navigation');
    history.replaceState({}, '', '/');
  });
});

describe('ui.input', () => {
  it('records the length bucket of a typed value and never the value', async () => {
    const input = document.createElement('input');
    input.dataset.el = 'ADV-REF-INPUT';
    document.body.append(input);

    input.value = 'DT4 8XX';
    input.dispatchEvent(new Event('input', { bubbles: true }));
    const events = await sentEvents();

    const typed = events.find((event) => event.name === 'ui.input');
    expect(typed?.attributes['element.id']).toBe('ADV-REF-INPUT');
    expect(typed?.attributes.length_bucket).toBe('6-20');
    expect(JSON.stringify(events)).not.toContain('DT4');
  });
});

describe('common attributes', () => {
  it('carry the role, the release, a session id kept in sessionStorage, and the device class', async () => {
    track('ui.chip', { 'element.id': 'FILTER-CHIP', state: 'on' });
    const events = await sentEvents();

    const [chip] = events;
    expect(chip?.attributes['user.role']).toBe('advisor');
    expect(chip?.attributes.release).toBe('test-release-1');
    expect(chip?.attributes['session.id']).toBe(sessionStorage.getItem('diucs.session.id'));
    expect(String(chip?.attributes['session.id'])).toMatch(/^[A-Za-z0-9-]{16,64}$/);
    expect(chip?.attributes['device.type']).toBe('desktop');
  });
});

describe('ui.page_view', () => {
  it('records the route template and how the page was loaded', async () => {
    trackPageView({ route: '/case/[ref]', from: '/board', loadType: 'navigate' });
    const events = await sentEvents();

    expect(events[0]?.name).toBe('ui.page_view');
    expect(events[0]?.attributes['page.route']).toBe('/case/[ref]');
    expect(events[0]?.attributes['from.route']).toBe('/board');
    expect(events[0]?.attributes['load.type']).toBe('navigate');
  });
});

describe('batching', () => {
  it('sends one beacon when the twentieth event is queued', () => {
    for (let i = 0; i < BATCH_SIZE; i += 1) {
      track('ui.chip', { 'element.id': 'FILTER-CHIP', state: 'on' });
    }

    expect(beacon).toHaveBeenCalledTimes(1);
    expect(beacon.mock.calls[0]?.[0]).toBe('/api/bff/telemetry');
  });

  it('sends three queued events after five seconds', async () => {
    for (let i = 0; i < 3; i += 1) {
      track('ui.chip', { 'element.id': 'FILTER-CHIP', state: 'on' });
    }
    expect(beacon).not.toHaveBeenCalled();

    await vi.advanceTimersByTimeAsync(FLUSH_MS);

    expect(beacon).toHaveBeenCalledTimes(1);
  });
});
