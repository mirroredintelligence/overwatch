// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { authorizeUrl, loadEntraConfig, newTransaction } from './oidc';
import { linkFields, sealTransaction, unsealTransaction } from './flow';
import { CLIENT_SECRET, ENTRA_ENV } from '@/test/oidc/constants';
import { TEST_SESSION_SECRET } from '@/test/cookies';

// An organisation's own sign-in link (DEC-1366). A guest from another organisation cannot be found by the shared
// `organizations` endpoint, which asks their own directory, so the link names the organisation's directory: that
// chooses only where Microsoft asks for the password. The tenant is still decided by the back end.

const DIRECTORY = 'c5901e0b-8d43-4ae8-97c3-ca6c52573a33';
const link = (query: string) => new Request(`https://overwatch.example.test/api/bff/auth/entra/start?${query}`);

describe('the organisation in a sign-in link', () => {
  beforeEach(() => {
    vi.stubEnv('ENTRA_CLIENT_SECRET', CLIENT_SECRET);
    vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  });
  afterEach(() => vi.unstubAllEnvs());

  it('is read as a directory id and lower-cased', () => {
    expect(linkFields(link(`org=${DIRECTORY.toUpperCase()}`)).directory).toBe(DIRECTORY);
  });

  it.each(['', 'organizations', 'common', 'contoso.onmicrosoft.com', `${DIRECTORY}/x`, '../x', DIRECTORY + 'a'])('ignores %j, as if none was named', (value) => {
    expect(linkFields(link(`org=${encodeURIComponent(value)}`)).directory).toBe('');
  });

  it('sends the sign-in to that directory, and to the shared endpoint when none is named', async () => {
    const config = await loadEntraConfig({ ...ENTRA_ENV });
    const named = authorizeUrl(config, newTransaction('', '', '', DIRECTORY));
    const shared = authorizeUrl(config, newTransaction(''));
    if (config.directoryId === null) {
      expect(named.pathname).toBe(`/${DIRECTORY}/oauth2/v2.0/authorize`);
      expect(shared.pathname).toBe('/organizations/oauth2/v2.0/authorize');
    } else {
      // A single-tenant registration always asks its own directory, whatever a link says.
      expect(named.pathname).toBe(shared.pathname);
    }
  });

  it('survives the sealed sign-in cookie, and a forged directory in it is refused', async () => {
    const now = new Date();
    const transaction = newTransaction('', '', '', DIRECTORY);
    const sealed = await sealTransaction(transaction, now);
    expect((await unsealTransaction(sealed, now))?.directory).toBe(DIRECTORY);
    const forged = await sealTransaction({ ...transaction, directory: 'organizations' }, now);
    expect(await unsealTransaction(forged, now)).toBeNull();
  });
});
