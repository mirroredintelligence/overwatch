import { describe, expect, it } from 'vitest';
import { QUEUE_TASKS } from '@/test/msw/handlers/clinical';
import { queueItemFromTask, urgencyText } from './queue';

describe('queueItemFromTask', () => {
  it('maps a queued request to its urgency, its reason and its case, and nothing about the people involved', () => {
    expect(queueItemFromTask(QUEUE_TASKS[0])).toEqual({
      id: 'req-4821',
      urgency: 'now',
      why: 'borderline-criteria',
      requestedAt: '2026-10-23T13:11:00Z',
      status: 'requested',
      caseId: 'case-4821',
    });
  });

  it('refuses a Task with an urgency it does not know', () => {
    const bad = { ...QUEUE_TASKS[0], extension: [{ url: 'https://diucs.example/CodeSystem/task-input/urgency', valueCode: 'soon' }] };
    expect(() => queueItemFromTask(bad)).toThrow('urgency is not known');
  });
});

describe('urgencyText', () => {
  it('says "Now" or "Within 15 min"', () => {
    expect(urgencyText('now')).toBe('Now');
    expect(urgencyText('within-15-min')).toBe('Within 15 min');
  });
});
