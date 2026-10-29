import { describe, expect, it } from 'vitest';
import { sameOrigin, syntheticTarget, type SyntheticEnv } from './guard';

// The synthetic checks may touch only an explicitly allow-listed test host (O09). These tests pin
// the guard: nothing runs against an unlisted host, and no secret appears in a reason. Sample
// values only.

const TOKEN = 'test-only-hook-token-0123456789';
const GOOD: SyntheticEnv = {
  SYNTHETIC_BASE_URL: 'https://diucs-test.example',
  SYNTHETIC_ALLOWED_HOSTS: 'diucs-test.example,diucs-test-api.example',
  SYNTHETIC_BACKEND_URL: 'https://diucs-test-api.example',
  SYNTHETIC_HOOK_TOKEN: TOKEN,
  SYNTHETIC_STAFF_STORAGE_STATE: '/run/secrets/synthetic-staff.json',
};

function withEnv(changes: SyntheticEnv): SyntheticEnv {
  return { ...GOOD, ...changes };
}

describe('syntheticTarget', () => {
  it('runs against an allow-listed https host with the hook token', () => {
    expect(syntheticTarget(GOOD)).toEqual({
      ok: true,
      baseUrl: 'https://diucs-test.example',
      backendUrl: 'https://diucs-test-api.example',
      hookToken: TOKEN,
      staffState: '/run/secrets/synthetic-staff.json',
    });
  });

  it('skips with a reason when the base URL is not set', () => {
    const result = syntheticTarget(withEnv({ SYNTHETIC_BASE_URL: undefined }));
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toContain('SYNTHETIC_BASE_URL');
  });

  it('skips with a reason when the host is not in SYNTHETIC_ALLOWED_HOSTS', () => {
    const result = syntheticTarget(withEnv({ SYNTHETIC_BASE_URL: 'https://diucs.example' }));
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.reason).toContain('not in SYNTHETIC_ALLOWED_HOSTS');
      expect(result.reason).toContain('diucs.example');
    }
  });

  it('refuses everything when the allow-list is empty', () => {
    expect(syntheticTarget(withEnv({ SYNTHETIC_ALLOWED_HOSTS: '' })).ok).toBe(false);
    expect(syntheticTarget(withEnv({ SYNTHETIC_ALLOWED_HOSTS: undefined })).ok).toBe(false);
  });

  it('matches hosts case-insensitively and ignores spaces in the list', () => {
    const result = syntheticTarget(
      withEnv({
        SYNTHETIC_BASE_URL: 'https://Diucs-Test.example/',
        SYNTHETIC_ALLOWED_HOSTS: '  other.example , DIUCS-TEST.example, Diucs-Test-Api.example ',
      }),
    );
    expect(result.ok).toBe(true);
  });

  it('does not treat a host that only contains an allowed host as allowed', () => {
    const result = syntheticTarget(
      withEnv({ SYNTHETIC_BASE_URL: 'https://diucs-test.example.attacker.example' }),
    );
    expect(result.ok).toBe(false);
  });

  it('refuses plain http unless the host is localhost and listed', () => {
    expect(
      syntheticTarget(
        withEnv({ SYNTHETIC_BASE_URL: 'http://diucs-test.example', SYNTHETIC_ALLOWED_HOSTS: 'diucs-test.example' }),
      ).ok,
    ).toBe(false);
    const local = syntheticTarget(
      withEnv({
        SYNTHETIC_BASE_URL: 'http://localhost:3000',
        SYNTHETIC_BACKEND_URL: 'http://localhost:4010',
        SYNTHETIC_ALLOWED_HOSTS: 'localhost:3000,localhost:4010',
      }),
    );
    expect(local.ok).toBe(true);
  });

  it('skips with a reason when the hook token or the back-end URL is missing', () => {
    const noToken = syntheticTarget(withEnv({ SYNTHETIC_HOOK_TOKEN: undefined }));
    expect(noToken.ok).toBe(false);
    if (!noToken.ok) expect(noToken.reason).toContain('SYNTHETIC_HOOK_TOKEN');
    const noBackend = syntheticTarget(withEnv({ SYNTHETIC_BACKEND_URL: undefined }));
    expect(noBackend.ok).toBe(false);
    if (!noBackend.ok) expect(noBackend.reason).toContain('SYNTHETIC_BACKEND_URL');
  });

  it('skips with a reason when the staff session file is not named', () => {
    const result = syntheticTarget(withEnv({ SYNTHETIC_STAFF_STORAGE_STATE: undefined }));
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toContain('SYNTHETIC_STAFF_STORAGE_STATE');
  });

  it('never puts the hook token in a reason', () => {
    const results = [
      syntheticTarget(withEnv({ SYNTHETIC_BASE_URL: 'not a url' })),
      syntheticTarget(withEnv({ SYNTHETIC_BASE_URL: 'https://diucs.example' })),
      syntheticTarget(withEnv({ SYNTHETIC_BACKEND_URL: 'ftp://diucs-test-api.example' })),
    ];
    for (const result of results) {
      expect(result.ok).toBe(false);
      if (!result.ok) expect(result.reason).not.toContain(TOKEN);
    }
  });
});

describe('sameOrigin', () => {
  it('accepts a link on the same origin, with any path and query', () => {
    expect(sameOrigin('https://diucs-test.example/l/abc?x=1', 'https://diucs-test.example')).toBe(true);
  });

  it('refuses a link on another host, another port or another scheme', () => {
    expect(sameOrigin('https://other.example/l/abc', 'https://diucs-test.example')).toBe(false);
    expect(sameOrigin('https://diucs-test.example:8443/l/abc', 'https://diucs-test.example')).toBe(false);
    expect(sameOrigin('http://diucs-test.example/l/abc', 'https://diucs-test.example')).toBe(false);
  });

  it('refuses text that is not a URL', () => {
    expect(sameOrigin('not a url', 'https://diucs-test.example')).toBe(false);
  });
});
