// Sample values for the staff sign-in tests. Directory ids and object ids are made up.

export const HOST = 'https://login.entra-fake.test';
export const PUBLIC_URL = 'https://capacity.example.test';
export const REDIRECT_URI = `${PUBLIC_URL}/api/bff/auth/entra/callback`;
export const CLIENT_ID = '5d1c7a0e-3f55-4a5b-9a41-2f3b6f0c9a11';
export const CLIENT_SECRET = 'fake-client-secret-for-tests-only';

// Two Entra directories, bound to two DIUCS tenants (W09 tenancy amendment).
export const DIRECTORY_A = '11111111-1111-4111-8111-111111111111';
export const DIRECTORY_B = '22222222-2222-4222-8222-222222222222';
// A directory nobody has bound to a tenant.
export const DIRECTORY_UNBOUND = '33333333-3333-4333-8333-333333333333';
// The operator's own directory, the only one that may carry the support role.
export const DIRECTORY_PLATFORM = '44444444-4444-4444-8444-444444444444';

export const TENANT_A = 'trust-a';
export const TENANT_B = 'trust-b';
export const TENANT_PLATFORM = 'platform-ops';

export const OID_ADVISOR = 'aaaaaaaa-0000-4000-8000-000000000001';
export const OID_LEAD = 'aaaaaaaa-0000-4000-8000-000000000002';
export const OID_B = 'bbbbbbbb-0000-4000-8000-000000000001';

// 32 bytes, base64. Test values only.
export const BACKEND_JWT_SECRET = Buffer.alloc(32, 5).toString('base64');

export const BINDINGS = JSON.stringify([
  { directoryId: DIRECTORY_A, tenantId: TENANT_A },
  { directoryId: DIRECTORY_B, tenantId: TENANT_B },
  { directoryId: DIRECTORY_PLATFORM, tenantId: TENANT_PLATFORM, platform: true },
]);

/** The one-directory variant: the sign-in then asks that directory directly. */
export const SINGLE_BINDING = JSON.stringify([{ directoryId: DIRECTORY_A, tenantId: TENANT_A }]);

export const ENTRA_ENV: Record<string, string> = {
  ENTRA_CLIENT_ID: CLIENT_ID,
  ENTRA_CLIENT_SECRET: CLIENT_SECRET,
  ENTRA_AUTHORITY_HOST: HOST,
  DIUCS_PUBLIC_URL: PUBLIC_URL,
  DIUCS_ENTRA_BINDINGS: BINDINGS,
  BACKEND_JWT_SECRET,
};
