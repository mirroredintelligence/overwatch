import { describe, expect, it } from 'vitest';
import { ADVISED_TASK, DONE_TASK, MINE_TASK, QUEUE_TASKS, UNREADABLE_TASK } from '@/test/msw/handlers/clinical';
import { clinicalRequestFromTask } from './task';

describe('clinicalRequestFromTask', () => {
  it('reads a waiting request with the case glance the back end sends', () => {
    expect(clinicalRequestFromTask(QUEUE_TASKS[0])).toEqual({
      id: 'req-4821',
      status: 'requested',
      urgency: 'now',
      why: 'borderline-criteria',
      requestedAt: '2026-10-23T13:11:00Z',
      caseId: 'case-4821',
      glance: { caseReference: '4821', ageBand: '80+', needs: ['frailty', 'fall-no-injury'], caseUrgency: 'within-2-hrs', news2: 2 },
      returnsAt: null,
      advice: null,
    });
  });

  it('reads when a held request returns to the queue', () => {
    const read = clinicalRequestFromTask(MINE_TASK);
    expect(read.status).toBe('in-progress');
    expect(read.returnsAt).toBe('2026-10-23T13:29:30Z');
  });

  it('reads the advice of an advised request: choice, reason, note and time', () => {
    expect(clinicalRequestFromTask(ADVISED_TASK).advice).toEqual({
      choice: 'go-ahead',
      reason: 'within-criteria-on-judgement',
      note: 'Phone the family first.',
      at: '2026-10-23T13:15:00Z',
    });
    expect(clinicalRequestFromTask(DONE_TASK).advice).toEqual({ choice: 'use-another-service', reason: null, note: null, at: '2026-10-23T12:50:00Z' });
  });

  it('has no glance when the Task carries no case number: the case could not be read', () => {
    expect(clinicalRequestFromTask(UNREADABLE_TASK).glance).toBeNull();
  });

  it('keeps a glance with only some parts: a missing age band or score is null, never guessed', () => {
    const partial = {
      ...QUEUE_TASKS[0],
      extension: (QUEUE_TASKS[0]!.extension as { url: string }[]).filter((item) => !/age-band|news2|need|case-urgency/.test(item.url)),
    };
    expect(clinicalRequestFromTask(partial).glance).toEqual({ caseReference: '4821', ageBand: null, needs: [], caseUrgency: null, news2: null });
  });

  it('refuses a value the back end never sends: an unknown status, an age band, a need, an advice choice', () => {
    const base = QUEUE_TASKS[0] as Record<string, unknown>;
    const ext = base.extension as { url: string }[];
    expect(() => clinicalRequestFromTask({ ...base, status: 'cancelled' })).toThrow();
    expect(() => clinicalRequestFromTask({ ...base, extension: [...ext, { url: 'https://diucs.example/CodeSystem/task-input/age-band', valueCode: '99+' }] })).toThrow();
    expect(() => clinicalRequestFromTask({ ...base, extension: [...ext, { url: 'https://diucs.example/CodeSystem/task-input/need', valueCode: 'shopping' }] })).toThrow();
    expect(() => clinicalRequestFromTask({ ...ADVISED_TASK, extension: [...ADVISED_TASK.extension.filter((item) => !/advice-choice/.test(item.url)), { url: 'https://diucs.example/CodeSystem/task-input/advice-choice', valueCode: 'shrug' }] })).toThrow();
  });

  it('never carries a postcode, a district or a practitioner, whatever the Task holds', () => {
    const read = clinicalRequestFromTask({ ...QUEUE_TASKS[0], owner: { reference: 'Practitioner/pr-1' }, requester: { reference: 'Practitioner/pr-2' }, extension: [...(QUEUE_TASKS[0]!.extension as unknown[]), { url: 'https://diucs.example/CodeSystem/task-input/postcode', valueString: 'DT4 8XX' }] });
    expect(JSON.stringify(read)).not.toMatch(/practitioner|DT4|postcode/i);
  });
});
