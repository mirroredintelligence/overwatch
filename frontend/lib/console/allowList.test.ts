import { describe, expect, it } from 'vitest';
import { pickAllowed } from './allowList';

// The console renders only the allow-listed fields of an event (W48). A value or a text field
// is never one of them, even when the API sends it.
describe('pickAllowed', () => {
  it('drops a value or text field from an event', () => {
    const event = pickAllowed({
      kind: 'ui.input',
      offsetMs: 44000,
      elementId: 'ADV-NEEDS-POSTCODE',
      value: 'DT4 8XX',
      text: 'Sample Patient',
    });

    expect(event).toEqual({ kind: 'ui.input', offsetMs: 44000, elementId: 'ADV-NEEDS-POSTCODE' });
    expect(JSON.stringify(event)).not.toMatch(/DT4|Sample Patient/);
  });

  it('keeps each allow-listed field that the API sends', () => {
    const event = pickAllowed({
      kind: 'api',
      offsetMs: 1200,
      route: '/api/bff/bookings',
      outcome: 'success',
      durationMs: 812,
      status: '201',
      traceId: '4bf92f3577b34da6a3ce929d0e0e4736',
    });

    expect(event).toEqual({
      kind: 'api',
      offsetMs: 1200,
      route: '/api/bff/bookings',
      outcome: 'success',
      durationMs: 812,
      status: '201',
      traceId: '4bf92f3577b34da6a3ce929d0e0e4736',
    });
  });

  it('refuses an event with no kind or no offset', () => {
    expect(pickAllowed({ offsetMs: 10 })).toBeNull();
    expect(pickAllowed({ kind: 'click' })).toBeNull();
  });
});
