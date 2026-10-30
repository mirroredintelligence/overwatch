// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { SESSION_COOKIE, sealSession } from '@/lib/auth/session';
import { resetCookieWrites, seedCookies, setRequestHost, TEST_SESSION_SECRET } from '@/test/cookies';
import { sessionFor } from '@/test/requests';
import { TENANTS } from '@/test/tenants';
import { Telemetry } from './Telemetry';
import { TelemetryMount } from './TelemetryMount';

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock, headers: m.headersMock };
});

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  resetCookieWrites();
  seedCookies({});
  setRequestHost(TENANTS.A.host);
});
afterEach(() => vi.unstubAllEnvs());

describe('Telemetry', () => {
  it('mounts the browser telemetry for a signed-in person, with the role of the session', async () => {
    seedCookies({ [SESSION_COOKIE]: await sealSession(sessionFor(TENANTS.A, 'advisor')) });

    const element = await Telemetry();

    expect(element?.type).toBe(TelemetryMount);
    expect(element?.props).toEqual({ role: 'advisor' });
  });

  it('mounts nothing for a signed-out page', async () => {
    expect(await Telemetry()).toBeNull();
  });

  it('mounts nothing for a session made on another host', async () => {
    seedCookies({ [SESSION_COOKIE]: await sealSession(sessionFor(TENANTS.A, 'advisor')) });
    setRequestHost(TENANTS.B.host);

    expect(await Telemetry()).toBeNull();
  });
});
