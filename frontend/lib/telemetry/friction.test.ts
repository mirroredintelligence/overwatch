import { describe, expect, it, vi } from 'vitest';
import { FRICTION_THRESHOLDS, QUICK_ACTION_ROUTES, createFrictionEngine, type FrictionEvent } from './friction';

// A clock the test moves by hand. The engine reads time only through now().
function harness() {
  let at = 0;
  const emitted: FrictionEvent[] = [];
  const emit = vi.fn((event: FrictionEvent) => {
    emitted.push(event);
  });
  const engine = createFrictionEngine({ now: () => at, emit });
  return {
    engine,
    emitted,
    emit,
    advance(ms: number) {
      at += ms;
    },
    kinds: () => emitted.map((event) => event.kind),
  };
}

describe('thresholds', () => {
  it('holds every starting value in one exported object', () => {
    expect(FRICTION_THRESHOLDS.rageClicks).toBe(3);
    expect(FRICTION_THRESHOLDS.rageWindowMs).toBe(1000);
    expect(FRICTION_THRESHOLDS.rageDistancePx).toBe(30);
    expect(FRICTION_THRESHOLDS.errorClickMs).toBe(2000);
    expect(FRICTION_THRESHOLDS.hesitationMs).toBe(20000);
    expect(FRICTION_THRESHOLDS.streamGapMs).toBe(10000);
    expect(QUICK_ACTION_ROUTES).toEqual(['/l/[token]', '/respond/[serviceId]', '/booking/[ref]']);
  });
});

describe('rage click', () => {
  it('fires on three clicks on the same element within 900 ms, with count 3', () => {
    const h = harness();
    const click = { elementId: 'ADV-OPT-REQUEST-BTN', x: 100, y: 100, interactive: true };

    h.engine.onClick(click);
    h.advance(450);
    h.engine.onClick(click);
    h.advance(450);
    h.engine.onClick(click);

    expect(h.emitted).toEqual([
      { kind: 'rage', 'element.id': 'ADV-OPT-REQUEST-BTN', count: 3, window_ms: 1000 },
    ]);
  });

  it('does not fire when the three clicks are 1.2 s apart', () => {
    const h = harness();
    const click = { elementId: 'ADV-OPT-REQUEST-BTN', x: 100, y: 100, interactive: true };

    h.engine.onClick(click);
    h.advance(1200);
    h.engine.onClick(click);
    h.advance(1200);
    h.engine.onClick(click);

    expect(h.kinds()).not.toContain('rage');
  });

  it('fires on three clicks 20 px apart on different elements within a second', () => {
    const h = harness();

    h.engine.onClick({ elementId: 'ADV-A-BTN', x: 100, y: 100, interactive: false });
    h.advance(300);
    h.engine.onClick({ elementId: 'ADV-B-BTN', x: 120, y: 100, interactive: false });
    h.advance(300);
    h.engine.onClick({ elementId: 'ADV-C-BTN', x: 140, y: 100, interactive: false });

    expect(h.kinds()).toContain('rage');
  });

  it('fires once for a burst, so a fourth click does not repeat it at once', () => {
    const h = harness();
    const click = { elementId: 'ADV-OPT-REQUEST-BTN', x: 100, y: 100, interactive: true };

    for (let i = 0; i < 4; i += 1) {
      h.engine.onClick(click);
      h.advance(100);
    }

    expect(h.kinds().filter((kind) => kind === 'rage')).toHaveLength(1);
  });
});

describe('dead click', () => {
  it('fires for an interactive click with result none after one second', () => {
    const h = harness();

    h.engine.onClick({ elementId: 'ADV-OPT-REQUEST-BTN', x: 0, y: 0, interactive: true });
    h.advance(1000);
    h.engine.onClickResult('ADV-OPT-REQUEST-BTN', 'none');

    expect(h.emitted).toContainEqual({ kind: 'dead', 'element.id': 'ADV-OPT-REQUEST-BTN', count: 1, window_ms: 1000 });
  });

  it('fires from tick when no result has arrived after one second', () => {
    const h = harness();

    h.engine.onClick({ elementId: 'ADV-OPT-REQUEST-BTN', x: 0, y: 0, interactive: true });
    h.advance(1000);
    h.engine.tick();

    expect(h.kinds()).toContain('dead');
  });

  it('does not fire when a navigation, network call or DOM change answers the click', () => {
    const h = harness();

    h.engine.onClick({ elementId: 'ADV-OPT-REQUEST-BTN', x: 0, y: 0, interactive: true });
    h.advance(200);
    h.engine.onClickResult('ADV-OPT-REQUEST-BTN', 'dom');
    h.advance(1000);
    h.engine.tick();

    expect(h.kinds()).not.toContain('dead');
  });

  it('does not fire for a click on something that is not interactive', () => {
    const h = harness();

    h.engine.onClick({ elementId: 'ADV-HEADING', x: 0, y: 0, interactive: false });
    h.advance(1000);
    h.engine.tick();

    expect(h.kinds()).not.toContain('dead');
  });
});

describe('error click', () => {
  it('fires when an HTTP 500 follows the click at 1.5 s', () => {
    const h = harness();

    h.engine.onClick({ elementId: 'ADV-OPT-REQUEST-BTN', x: 0, y: 0, interactive: true });
    h.advance(1500);
    h.engine.onRequestEnd('ADV-OPT-REQUEST-BTN', 500);

    expect(h.emitted).toContainEqual({
      kind: 'error-click',
      'element.id': 'ADV-OPT-REQUEST-BTN',
      count: 1,
      window_ms: 2000,
    });
  });

  it('does not fire when the error comes at 2.5 s', () => {
    const h = harness();

    h.engine.onClick({ elementId: 'ADV-OPT-REQUEST-BTN', x: 0, y: 0, interactive: true });
    h.advance(2500);
    h.engine.onRequestEnd('ADV-OPT-REQUEST-BTN', 500);

    expect(h.kinds()).not.toContain('error-click');
  });

  it('fires for a script error and for an error message within two seconds', () => {
    const h = harness();

    h.engine.onClick({ elementId: 'ADV-OPT-SAVE-BTN', x: 0, y: 0, interactive: true });
    h.advance(500);
    h.engine.onError('ADV-OPT-SAVE-BTN');

    expect(h.kinds()).toEqual(['error-click']);
  });

  it('answers one click once, so a second error does not repeat it', () => {
    const h = harness();

    h.engine.onClick({ elementId: 'ADV-OPT-SAVE-BTN', x: 0, y: 0, interactive: true });
    h.advance(300);
    h.engine.onRequestEnd('ADV-OPT-SAVE-BTN', 500);
    h.engine.onError('ADV-OPT-SAVE-BTN');

    expect(h.kinds().filter((kind) => kind === 'error-click')).toHaveLength(1);
  });

  it('does not fire for a 2xx response', () => {
    const h = harness();

    h.engine.onClick({ elementId: 'ADV-OPT-SAVE-BTN', x: 0, y: 0, interactive: true });
    h.advance(300);
    h.engine.onRequestEnd('ADV-OPT-SAVE-BTN', 200);

    expect(h.kinds()).not.toContain('error-click');
  });
});

describe('impatient click', () => {
  it('fires when a second click lands on the control while its first request is in flight', () => {
    const h = harness();
    const click = { elementId: 'ADV-OPT-REQUEST-BTN', x: 0, y: 0, interactive: true };

    h.engine.onClick(click);
    h.engine.onRequestStart('ADV-OPT-REQUEST-BTN');
    h.advance(400);
    h.engine.onClick(click);

    expect(h.emitted).toContainEqual({
      kind: 'impatient',
      'element.id': 'ADV-OPT-REQUEST-BTN',
      count: 2,
      window_ms: 400,
    });
  });

  it('does not fire once the first request has ended', () => {
    const h = harness();
    const click = { elementId: 'ADV-OPT-REQUEST-BTN', x: 0, y: 0, interactive: true };

    h.engine.onClick(click);
    h.engine.onRequestStart('ADV-OPT-REQUEST-BTN');
    h.advance(400);
    h.engine.onRequestEnd('ADV-OPT-REQUEST-BTN', 200);
    h.advance(400);
    h.engine.onClick(click);

    expect(h.kinds()).not.toContain('impatient');
  });
});

describe('u-turn', () => {
  it('fires for /case/[ref] to /case/[ref]/options and back within 5 s with no interaction on the options page', () => {
    const h = harness();

    h.engine.onRoute('/case/[ref]');
    h.advance(1000);
    h.engine.onRoute('/case/[ref]/options');
    h.advance(3000);
    h.engine.onRoute('/case/[ref]');

    expect(h.emitted).toContainEqual({ kind: 'u-turn', 'element.id': 'PAGE', count: 1, window_ms: 5000 });
  });

  it('does not fire when the person used the options page before going back', () => {
    const h = harness();

    h.engine.onRoute('/case/[ref]');
    h.advance(1000);
    h.engine.onRoute('/case/[ref]/options');
    h.advance(500);
    h.engine.onClick({ elementId: 'ADV-OPT-CHOOSE-BTN', x: 0, y: 0, interactive: true });
    h.advance(1000);
    h.engine.onRoute('/case/[ref]');

    expect(h.kinds()).not.toContain('u-turn');
  });
});

describe('thrash', () => {
  it('fires for three switches between the same two routes within 10 s', () => {
    const h = harness();

    h.engine.onRoute('/board');
    h.advance(1000);
    h.engine.onRoute('/case/[ref]');
    h.advance(1000);
    h.engine.onRoute('/board');
    h.advance(1000);
    h.engine.onRoute('/case/[ref]');

    expect(h.kinds()).toContain('thrash');
  });
});

describe('validation loop', () => {
  it('fires when the same field fails validation three times', () => {
    const h = harness();

    h.engine.onValidation('ADV-NEEDS-POSTCODE', false);
    h.engine.onValidation('ADV-NEEDS-POSTCODE', false);
    h.engine.onValidation('ADV-NEEDS-POSTCODE', false);

    expect(h.emitted).toEqual([
      { kind: 'validation-loop', 'element.id': 'ADV-NEEDS-POSTCODE', count: 3, window_ms: 0 },
    ]);
  });

  it('starts counting again after the field is valid', () => {
    const h = harness();

    h.engine.onValidation('ADV-NEEDS-POSTCODE', false);
    h.engine.onValidation('ADV-NEEDS-POSTCODE', false);
    h.engine.onValidation('ADV-NEEDS-POSTCODE', true);
    h.engine.onValidation('ADV-NEEDS-POSTCODE', false);

    expect(h.kinds()).not.toContain('validation-loop');
  });
});

describe('form abandonment', () => {
  it('records the last focused field when the person leaves without submitting', () => {
    const h = harness();

    h.engine.onFocus('ADV-NEEDS-POSTCODE');
    h.advance(2000);
    h.engine.onLeave();

    expect(h.emitted).toEqual([
      { kind: 'abandonment', 'element.id': 'ADV-NEEDS-POSTCODE', count: 1, window_ms: 2000 },
    ]);
  });

  it('does not fire when the form was submitted before leaving', () => {
    const h = harness();

    h.engine.onFocus('ADV-NEEDS-POSTCODE');
    h.engine.onSubmit();
    h.engine.onLeave();

    expect(h.kinds()).not.toContain('abandonment');
  });
});

describe('hesitation', () => {
  it('fires after 21 s with no interaction on /l/[token]', () => {
    const h = harness();

    h.engine.onRoute('/l/[token]');
    h.advance(21000);
    h.engine.tick();

    expect(h.emitted).toEqual([{ kind: 'hesitation', 'element.id': 'PAGE', count: 1, window_ms: 20000 }]);
  });

  it('does not fire on /case/[ref], which is not a quick-action screen', () => {
    const h = harness();

    h.engine.onRoute('/case/[ref]');
    h.advance(21000);
    h.engine.tick();

    expect(h.kinds()).not.toContain('hesitation');
  });

  it('fires once per idle period', () => {
    const h = harness();

    h.engine.onRoute('/l/[token]');
    h.advance(21000);
    h.engine.tick();
    h.advance(5000);
    h.engine.tick();

    expect(h.kinds().filter((kind) => kind === 'hesitation')).toHaveLength(1);
  });
});

describe('missed tap', () => {
  it('fires for a tap within 24 px of a control that did not land on it', () => {
    const h = harness();

    h.engine.onClick({
      elementId: 'PAGE-TEXT',
      x: 10,
      y: 10,
      interactive: false,
      missed: { elementId: 'ADV-OPT-REQUEST-BTN', distancePx: 12 },
    });

    expect(h.emitted).toEqual([
      { kind: 'missed-tap', 'element.id': 'ADV-OPT-REQUEST-BTN', count: 1, window_ms: 0 },
    ]);
  });

  it('does not fire for a tap 30 px from the nearest control', () => {
    const h = harness();

    h.engine.onClick({
      elementId: 'PAGE-TEXT',
      x: 10,
      y: 10,
      interactive: false,
      missed: { elementId: 'ADV-OPT-REQUEST-BTN', distancePx: 30 },
    });

    expect(h.kinds()).not.toContain('missed-tap');
  });
});

describe('scroll thrash', () => {
  it('fires on four reversals of scroll direction inside 3 s', () => {
    const h = harness();

    h.engine.onScroll('down');
    h.advance(300);
    h.engine.onScroll('up');
    h.advance(300);
    h.engine.onScroll('down');
    h.advance(300);
    h.engine.onScroll('up');
    h.advance(300);
    h.engine.onScroll('down');

    expect(h.emitted).toEqual([{ kind: 'scroll-thrash', 'element.id': 'PAGE', count: 4, window_ms: 3000 }]);
  });

  it('does not fire for a steady scroll with no reversals', () => {
    const h = harness();

    for (let i = 0; i < 10; i += 1) {
      h.engine.onScroll('down');
      h.advance(100);
    }

    expect(h.kinds()).not.toContain('scroll-thrash');
  });
});

describe('stream gap', () => {
  it('fires when the live stream is down for 11 s while the page is open', () => {
    const h = harness();

    h.engine.onStream('open');
    h.engine.onStream('down');
    h.advance(11000);
    h.engine.tick();

    expect(h.emitted).toEqual([{ kind: 'stream-gap', 'element.id': 'LIVE-STREAM', count: 1, window_ms: 11000 }]);
  });

  it('does not fire for an outage of 9 s', () => {
    const h = harness();

    h.engine.onStream('down');
    h.advance(9000);
    h.engine.onStream('open');
    h.engine.tick();

    expect(h.kinds()).not.toContain('stream-gap');
  });
});
