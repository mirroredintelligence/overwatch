// Sample values for the staff sign-in tests. Directory ids and object ids are made up.

export const HOST = 'https://login.entra-fake.test';
// One sub-domain per tenant (DEC-134 item 3): the site a person signs in on is the tenant's own host,
// and the redirect URI the sign-in sends to the provider is built from it.
export const PUBLIC_URL = 'https://tenant-a.example.test';
export const PUBLIC_URL_B = 'https://tenant-b.example.test';
export const PUBLIC_URL_C = 'https://tenant-c.example.test';
export const CALLBACK_PATH = '/api/bff/auth/entra/callback';
export const REDIRECT_URI = `${PUBLIC_URL}${CALLBACK_PATH}`;
export const REDIRECT_URI_B = `${PUBLIC_URL_B}${CALLBACK_PATH}`;
export const REDIRECT_URI_C = `${PUBLIC_URL_C}${CALLBACK_PATH}`;
export const CLIENT_ID = '5d1c7a0e-3f55-4a5b-9a41-2f3b6f0c9a11';
export const CLIENT_SECRET = 'fake-client-secret-for-tests-only';

// Two Entra directories, each bound by one tenant, and one that no tenant has bound. The binding is the
// back end's (TEN-043): the front end holds no list of directories.
export const DIRECTORY_A = '11111111-1111-4111-8111-111111111111';
export const DIRECTORY_B = '22222222-2222-4222-8222-222222222222';
export const DIRECTORY_UNBOUND = '33333333-3333-4333-8333-333333333333';

export const TENANT_A = 'trust-a';
export const TENANT_B = 'trust-b';

export const OID_ADVISOR = 'aaaaaaaa-0000-4000-8000-000000000001';
export const OID_LEAD = 'aaaaaaaa-0000-4000-8000-000000000002';
export const OID_B = 'bbbbbbbb-0000-4000-8000-000000000001';

/** What the sign-in reads: the provider and this app's registration. No tenant, no directory list, no signing secret. */
export const ENTRA_ENV: Record<string, string> = {
  ENTRA_CLIENT_ID: CLIENT_ID,
  ENTRA_CLIENT_SECRET: CLIENT_SECRET,
  ENTRA_AUTHORITY_HOST: HOST,
};
