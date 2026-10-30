import { describe, expect, it } from 'vitest';
import { QUEUE_TASKS, UNREADABLE_TASK } from '@/test/msw/handlers/clinical';
import { queueItemFromTask, summaryLine, urgencyText } from './queue';

describe('queueItemFromTask', () => {
  it('maps a queued request to its urgency, its reason, its case glance and nothing about the people involved', () => {
    expect(queueItemFromTask(QUEUE_TASKS[0])).toMatchObject({
      id: 'req-4821',
      urgency: 'now',
      why: 'borderline-criteria',
      requestedAt: '2026-10-23T13:11:00Z',
      status: 'requested',
      caseId: 'case-4821',
      glance: { caseReference: '4821', news2: 2 },
    });
  });

  it('refuses a Task with an urgency it does not know', () => {
    const bad = { ...QUEUE_TASKS[0], extension: [{ url: 'https://diucs.example/CodeSystem/task-input/urgency', valueCode: 'soon' }] };
    expect(() => queueItemFromTask(bad)).toThrow('urgency is not known');
  });
});

describe('summaryLine', () => {
  it('says age band, needs, NEWS2 and the case urgency, as the advisor recorded them', () => {
    expect(summaryLine(queueItemFromTask(QUEUE_TASKS[0]).glance)).toBe('80+ · Frailty, Fall · NEWS2 2 · Within 2 hrs');
  });

  it('leaves out what was not recorded, and is null when the case could not be read', () => {
    expect(summaryLine({ caseReference: '4821', ageBand: null, needs: [], caseUrgency: null, news2: null })).toBe('');
    expect(summaryLine(queueItemFromTask(UNREADABLE_TASK).glance)).toBeNull();
  });
});

describe('urgencyText', () => {
  it('says "Now" or "Within 15 min"', () => {
    expect(urgencyText('now')).toBe('Now');
    expect(urgencyText('within-15-min')).toBe('Within 15 min');
  });
});
