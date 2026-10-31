// Sample values for the staff sign-in tests. Directory ids and object ids are made up.

export const HOST = 'https://login.entra-fake.test';
export const PUBLIC_URL = 'https://capacity.example.test';
export const REDIRECT_URI = `${PUBLIC_URL}/api/bff/auth/entra/callback`;
export const CLIENT_ID = '5d1c7a0e-3f55-4a5b-9a41-2f3b6f0c9a11';
export const CLIENT_SECRET = 'fake-client-secret-for-tests-only';

// Entra directories. Which of them a DIUCS tenant has bound is the back end's record (TEN-043); the
// front end holds no table of it. The stand-in back end (test/fixtures/exchange.ts) knows the grants.
export const DIRECTORY_A = '11111111-1111-4111-8111-111111111111';
export const DIRECTORY_B = '22222222-2222-4222-8222-222222222222';
// A directory no tenant has bound.
export const DIRECTORY_UNBOUND = '33333333-3333-4333-8333-333333333333';
// The operator's own directory, the only one that may carry the support role.
export const DIRECTORY_PLATFORM = '44444444-4444-4444-8444-444444444444';


export const OID_ADVISOR = 'aaaaaaaa-0000-4000-8000-000000000001';
export const OID_LEAD = 'aaaaaaaa-0000-4000-8000-000000000002';
export const OID_B = 'bbbbbbbb-0000-4000-8000-000000000001';

// The back end the BFF calls (as the link tests do): its address, and the host the sign-in is
// served on, which is the host the back end takes the tenant from (DEC-134 item 3, TEN-043).
export const BACKEND_ROOT = 'http://backend.test';
export const SIGN_IN_HOST = new URL(PUBLIC_URL).host;

export const ENTRA_ENV: Record<string, string> = {
  ENTRA_CLIENT_ID: CLIENT_ID,
  ENTRA_CLIENT_SECRET: CLIENT_SECRET,
  ENTRA_AUTHORITY_HOST: HOST,
  DIUCS_PUBLIC_URL: PUBLIC_URL,
  DIUCS_FHIR_BASE_URL: `${BACKEND_ROOT}/fhir`,
};

// The operator console's own sign-in (TEN-083): another app registration for the operator's directory
// only, served on its own host. The operator exchange (`POST /auth/operator-token`) takes no tenant.
export const OPERATOR_CLIENT_ID = '6e2d8b1f-4a66-4b6c-8b52-3a4c7f1d0b22';
export const OPERATOR_CLIENT_SECRET = 'fake-operator-client-secret-for-tests-only';
export const OPERATOR_PUBLIC_URL = 'https://console.example.test';
export const OPERATOR_HOST_NAME = new URL(OPERATOR_PUBLIC_URL).host;
export const OPERATOR_REDIRECT_URI = `${OPERATOR_PUBLIC_URL}/api/bff/platform/auth/callback`;
export const OID_OPERATOR = 'bbbbbbbb-0000-4000-8000-0000000000a1';
export const OID_SUPPORT = 'bbbbbbbb-0000-4000-8000-0000000000a2';

export const OPERATOR_ENV: Record<string, string> = {
  OPERATOR_ENTRA_CLIENT_ID: OPERATOR_CLIENT_ID,
  OPERATOR_ENTRA_CLIENT_SECRET: OPERATOR_CLIENT_SECRET,
  OPERATOR_ENTRA_DIRECTORY_ID: DIRECTORY_PLATFORM,
  DIUCS_OPERATOR_PUBLIC_URL: OPERATOR_PUBLIC_URL,
  ENTRA_AUTHORITY_HOST: HOST,
  DIUCS_FHIR_BASE_URL: `${BACKEND_ROOT}/fhir`,
};
