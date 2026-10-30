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
    });
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
      raisedAt: '2026-10-23T13:04:00Z', state: 'new', escalatesAt: null, escalatesTo: null,
    };
    expect(alertTitle(item)).toBe('Hospital at home over capacity');
    expect(alertTitle({ ...item, serviceName: null })).toBe('A service over capacity');
  });
});
