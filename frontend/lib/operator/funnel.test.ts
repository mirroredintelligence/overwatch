import { describe, expect, it } from 'vitest';
import { RAW_DETAIL_PROVISIONING, RAW_DETAIL_READY, viewOf } from '@/test/fixtures/operator';
import { deriveFunnel, STEP_TITLES, type ConsentRead } from './funnel';

// The Go live funnel: the agreements are recommended and never left (DEC-1319), a stopped number counts for nothing, and
// the shared line counts only once a test text has been sent on it.

const CONSENTED: ConsentRead = { status: 'ok', data: { invitation: { emailMasked: 'j***@example.test', status: 'consented', createdAt: '2026-11-01T09:00:00Z', expiresAt: '2026-11-08T09:00:00Z', consentedAt: '2026-11-02T10:00:00Z', reason: null } } as never };
const none = { dsa: null, dpia: null, dcb0160: null };
const derive = (detail: unknown, consent: ConsentRead) => deriveFunnel(detail as Parameters<typeof deriveFunnel>[0], consent);

function withTenant(raw: typeof RAW_DETAIL_READY, over: Record<string, unknown>) {
  const view = viewOf(raw);
  return { ...view, ...over } as unknown as { tenant: Record<string, unknown> } & Record<string, unknown>;
}

describe('agreements are recommended', () => {
  it('names the step as recommended and counts the ones not recorded', () => {
    expect(STEP_TITLES.agreements).toBe('Agreements (recommended)');
    const detail = withTenant(RAW_DETAIL_READY, {});
    detail.tenant = { ...detail.tenant, references: none };
    const funnel = derive(detail, CONSENTED);
    expect(funnel.recommended).toBe(3);
    expect(funnel.steps.find((s) => s.id === 'agreements')).toMatchObject({ done: true, missing: [] });
  });

  it('never lists them as left, and never stops go live', () => {
    const detail = withTenant(RAW_DETAIL_READY, {});
    detail.tenant = { ...detail.tenant, references: none };
    const funnel = derive(detail, CONSENTED);
    expect(funnel.missing.filter((m) => m.step === 'agreements')).toEqual([]);
    expect(funnel.leftByPhase).toEqual([]);
    expect(funnel.canGoLive).toBe(true);
  });

  it('says the part’s summary with the word recommended', () => {
    const funnel = derive(viewOf(RAW_DETAIL_PROVISIONING), CONSENTED);
    const reach = funnel.phases.find((p) => p.id === 'reach')!;
    expect(reach.summary).toContain('Agreements (recommended) 1 of 3.');
  });

  it('ignores a back end sentence about references, which it no longer sends', () => {
    const detail = withTenant(RAW_DETAIL_READY, { activation: { ready: false, blockers: ['Data sharing, data protection and clinical safety references recorded'] } });
    const funnel = derive(detail, CONSENTED);
    expect(funnel.missing.some((m) => m.step === 'agreements')).toBe(false);
  });
});

describe('which text lines count', () => {
  it('counts a stopped number for nothing, even tested', () => {
    const detail = withTenant(RAW_DETAIL_READY, { numbers: viewOf(RAW_DETAIL_READY).numbers.map((n) => ({ ...n, status: 'retired' })) });
    const funnel = derive(detail, CONSENTED);
    expect(funnel.missing.some((m) => m.key === 'number')).toBe(true);
    expect(funnel.canGoLive).toBe(false);
  });

  it('counts the shared line only after a test text has been sent on it', () => {
    const base = { numbers: [] as never[], sharedLine: { status: 'active' as const, testedAt: null as string | null } };
    const untested = derive(withTenant(RAW_DETAIL_READY, base), CONSENTED);
    expect(untested.missing.some((m) => m.key === 'number')).toBe(true);
    const tested = derive(withTenant(RAW_DETAIL_READY, { ...base, sharedLine: { status: 'active', testedAt: '2026-11-02T10:00:00Z' } }), CONSENTED);
    expect(tested.missing.some((m) => m.key === 'number')).toBe(false);
    expect(tested.phases.find((p) => p.id === 'reach')!.summary).toContain('Text number tested');
  });
});
