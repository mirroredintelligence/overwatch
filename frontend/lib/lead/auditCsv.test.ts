import { describe, expect, it } from 'vitest';
import { AUDIT_4821 } from '@/test/fixtures/lead';
import { toCsv } from './auditCsv';

describe('toCsv', () => {
  it('starts with a header row, one row per shown service, then one per timeline entry', () => {
    const lines = toCsv(AUDIT_4821).split('\r\n');
    expect(lines[0]).toBe('Type,Time,Service,Status,Figure,Data age,Criteria version,Event');
    expect(lines[1]).toBe('shown,2026-10-23T13:13:20Z,UCR West,Accepting,4,9 min old,3,');
    expect(lines).toHaveLength(1 + AUDIT_4821.shown.length + AUDIT_4821.timeline.length + 1);
  });

  it('quotes a service name that holds a comma, and doubles a quote inside a field', () => {
    const csv = toCsv({
      ...AUDIT_4821,
      shown: [{ serviceName: 'UCR West, "north"', status: 'Accepting', value: '4', age: '9 min old' }],
      criteriaVersions: [{ serviceName: 'UCR West, "north"', version: 3 }],
    });
    expect(csv).toContain('shown,2026-10-23T13:13:20Z,"UCR West, ""north""",Accepting,4,9 min old,3,');
  });

  it('gives a field that starts with a formula character an apostrophe, so a spreadsheet does not run it', () => {
    const csv = toCsv({ ...AUDIT_4821, shown: [{ serviceName: '=HYPERLINK("x")', status: 'Accepting', value: '4', age: '9 min old' }], criteriaVersions: [] });
    expect(csv).toContain(`shown,2026-10-23T13:13:20Z,"'=HYPERLINK(""x"")",Accepting,4,9 min old,,`);
  });

  it('never holds a postcode, because none is in the replay it is given', () => {
    expect(toCsv(AUDIT_4821)).not.toMatch(/\bDT\d/);
  });
});
