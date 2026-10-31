import { describe, expect, it } from 'vitest';
import { canAccess, rolesFor } from '@/lib/auth/access';

// The radar and coverage pages sit under prefixes the role guard already holds, so no new door is opened:
// the radar views are the advisor's call flow, the coverage view is the planning view's audience, and the
// coverage form is the shift lead's.

describe('who may open the radar and coverage pages', () => {
  it.each(['radar', 'compare', 'ways'])('/advisor/case/<id>/%s is for the advisor alone', (view) => {
    const path = `/advisor/case/case-1/${view}`;
    expect(rolesFor(path)).toEqual(['advisor']);
    expect(canAccess('advisor', path)).toBe(true);
    for (const role of ['lead', 'exec', 'clinical', 'owner', 'support'] as const) expect(canAccess(role, path)).toBe(false);
  });

  it('/planning/coverage is for the lead and the executive', () => {
    expect(rolesFor('/planning/coverage')).toEqual(['exec', 'lead']);
    expect(canAccess('advisor', '/planning/coverage')).toBe(false);
  });

  it('/lead/coverage/<service> is for the lead alone', () => {
    expect(rolesFor('/lead/coverage/svc-ucr-west')).toEqual(['lead']);
    expect(canAccess('exec', '/lead/coverage/svc-ucr-west')).toBe(false);
  });
});
