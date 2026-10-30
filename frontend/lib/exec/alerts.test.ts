import { describe, expect, it } from 'vitest';
import type { BoardEntry } from '@/lib/board/types';
import { alertItemFromTask, alertTitle, type AlertItem } from './alerts';

const task = {
  resourceType: 'Task',
  id: 'al-1',
  status: 'requested',
  code: { coding: [{ system: 'https://diucs.example/CodeSystem/task-code', code: 'acknowledge-alert' }] },
  businessStatus: { coding: [{ system: 'https://diucs.example/CodeSystem/alert-status', code: 'escalated' }] },
  owner: { reference: 'Practitioner/pr-0042' },
  authoredOn: '2026-10-23T13:04:00+00:00',
  focus: { reference: 'HealthcareService/svc-hah' },
  executionPeriod: { end: '2026-10-23T13:19:00+00:00' },
  extension: [{ url: 'https://diucs.example/CodeSystem/alert-kind', valueCode: 'over-capacity' }],
};

const entry = { serviceId: 'svc-hah', name: 'Hospital at home', overBy: 4 } as BoardEntry;

describe('alertItemFromTask', () => {
  it('maps an alert Task to the screens shape, with the service name and the escalation time from the board', () => {
    const item = alertItemFromTask(task, (id) => (id === 'svc-hah' ? entry : undefined));
    expect(item).toEqual({
      id: 'al-1',
      kind: 'over-capacity',
      serviceId: 'svc-hah',
      serviceName: 'Hospital at home',
      detail: '+4',
      raisedAt: '2026-10-23T13:04:00Z',
      state: 'escalated',
      escalatesAt: '2026-10-23T13:19:00Z',
      escalatesTo: 'deputy',
      acknowledgedAt: null,
    });
  });

  it('reads an acknowledged alert with when it was acknowledged', () => {
    const acknowledged = {
      ...task,
      status: 'completed',
      businessStatus: { coding: [{ code: 'acknowledged' }] },
      executionPeriod: undefined,
      extension: [
        ...task.extension,
        { url: 'https://diucs.example/CodeSystem/alert-acknowledged-at', valueDateTime: '2026-10-23T13:40:00+00:00' },
      ],
    };
    const item = alertItemFromTask(acknowledged, () => undefined);
    expect(item.state).toBe('acknowledged');
    expect(item.acknowledgedAt).toBe('2026-10-23T13:40:00Z');
    expect(item.escalatesAt).toBeNull();
  });

  it('reads a closed alert, with no acknowledgement time when it was never acknowledged', () => {
    const item = alertItemFromTask({ ...task, status: 'completed', businessStatus: { coding: [{ code: 'closed' }] } }, () => undefined);
    expect(item.state).toBe('closed');
    expect(item.acknowledgedAt).toBeNull();
  });

  it('refuses a status it does not know', () => {
    expect(() => alertItemFromTask({ ...task, businessStatus: { coding: [{ code: 'snoozed' }] } }, () => undefined)).toThrow();
  });

  it('leaves the name and detail empty when the board does not hold the service', () => {
    const item = alertItemFromTask(task, () => undefined);
    expect(item.serviceName).toBeNull();
    expect(item.detail).toBeNull();
  });

  it('refuses a Task with no alert kind it knows, rather than showing it', () => {
    expect(() => alertItemFromTask({ ...task, extension: [] }, () => undefined)).toThrow();
  });
});

describe('alertTitle', () => {
  it('names the service and what happened', () => {
    const item: AlertItem = {
      id: 'x', kind: 'over-capacity', serviceId: 's', serviceName: 'Hospital at home', detail: '+4',
      raisedAt: '2026-10-23T13:04:00Z', state: 'new', escalatesAt: null, escalatesTo: null, acknowledgedAt: null,
    };
    expect(alertTitle(item)).toBe('Hospital at home over capacity');
    expect(alertTitle({ ...item, serviceName: null })).toBe('A service over capacity');
  });
});
