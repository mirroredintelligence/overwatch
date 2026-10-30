// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { BACKEND_ROOT } from '@/test/fixtures/links';
import { answerBackend, resetSeen, seen } from '@/test/applicant/backend';
import { callerRequest } from '@/test/applicant/session';
import { TEST_SESSION_SECRET } from '@/test/cookies';
import { withApplicantHandlers } from '@/test/msw/applicant';
import { PUT } from './route';

withApplicantHandlers();

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock };
});

// Saving one step (W54 to W26). The browser sends its answers; the BFF maps them to the back end's
// step values. The organisation's name and ODS code are typed by the applicant (DEC-910): the review
// checks them. A field the back end cannot keep is never sent (DEC-906). "Save draft" is a partial
// $draft (DEC-905). A refusal comes back as the errors each field shows.

const ID = 'REG-SAMPLE-1';
const ctx = (id: string, step: string) => ({ params: Promise.resolve({ id, step }) });
const url = (step: string) => `https://tenant-a.example.test/api/bff/registrations/${ID}/steps/${step}`;

function draftAnswer(status: number, body: unknown) {
  answerBackend('put', `/fhir/Task/${ID}/$draft`, status, body);
}

const TASK = { resourceType: 'Task', id: ID, businessStatus: { coding: [{ system: 'x', code: 'draft' }] } };

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', `${BACKEND_ROOT}/fhir`);
  resetSeen();
  draftAnswer(200, TASK);
});

async function save(step: string, body: unknown) {
  return PUT(await callerRequest(url(step), 'reporter', { method: 'PUT', body }), ctx(ID, step));
}

describe('PUT /api/bff/registrations/[id]/steps/organisation', () => {
  it('sends the typed name and ODS code, the organisation type and the contact, and answers the status', async () => {
    const response = await save('organisation', { name: 'Sample Community Trust', odsCode: 'SAM01', orgType: 'nhs-trust', contactName: 'Sam Sample', contact: 'sam@example.test' });
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ status: 'draft' });
    const sent = seen.find((call) => call.path === `/fhir/Task/${ID}/$draft`);
    expect(sent?.body).toEqual({
      step: 'organisation',
      values: { name: 'Sample Community Trust', odsCode: 'SAM01', orgType: 'nhs-trust', contactName: 'Sam Sample', contactEmail: 'sam@example.test' },
    });
    expect(sent?.auth).toBe('Bearer backend-token-sample-value');
  });

  it('never sends the contact role, which the back end cannot keep', async () => {
    const response = await save('organisation', { name: 'Sample Community Trust', odsCode: 'SAM01', orgType: 'nhs-trust', contactName: 'Sam Sample', contactRole: 'Practice manager', contact: '07700900456' });
    expect(response.status).toBe(200);
    const sent = seen.find((call) => call.path === `/fhir/Task/${ID}/$draft`);
    expect(JSON.stringify(sent?.body)).not.toContain('Practice manager');
    expect(sent?.body).toMatchObject({ values: { contactPhone: '07700900456' } });
  });

  it('sends a partial save as partial, and answers what is still missing', async () => {
    draftAnswer(200, { ...TASK, incomplete: [{ field: 'odsCode', message: 'Enter the ODS code' }] });
    const response = await save('organisation', { name: 'Sample Community Trust', partial: true });
    expect(response.status).toBe(200);
    expect(seen.find((call) => call.path === `/fhir/Task/${ID}/$draft`)?.body).toMatchObject({ step: 'organisation', partial: true });
    expect(await response.json()).toEqual({ status: 'draft', incomplete: [{ field: 'odsCode', message: 'Enter the ODS code' }] });
  });

  it('answers the back end’s refusal as 422 with the errors on the fields it names, in the page’s names', async () => {
    draftAnswer(400, {
      resourceType: 'OperationOutcome',
      issue: [
        { severity: 'error', code: 'invalid', diagnostics: 'Enter the ODS code', expression: ['odsCode'] },
        { severity: 'error', code: 'invalid', diagnostics: 'Enter an email address or phone number', expression: ['contactEmail'] },
      ],
    });
    const response = await save('organisation', { name: 'Sample Community Trust', odsCode: 'bad' });
    expect(response.status).toBe(422);
    expect(await response.json()).toEqual({
      errors: [
        { field: 'odsCode', message: 'Enter the ODS code' },
        { field: 'contact', message: 'Enter an email address or phone number' },
      ],
    });
  });

  it('refuses a body with a field the step does not take, without calling the back end', async () => {
    const response = await save('organisation', { name: 'Sample Community Trust', tenantId: 'other' });
    expect(response.status).toBe(400);
    expect(seen.some((call) => call.path.includes('$draft'))).toBe(false);
  });
});

describe('PUT /api/bff/registrations/[id]/steps/location', () => {
  it('sends the fixed site in the back end’s names, and never the UPRN or the site’s ODS code', async () => {
    const response = await save('location', {
      fixedSite: true,
      postcode: 'dt48xx',
      addressId: '100090001',
      address: '1 High Street, Dorchester',
      siteName: 'Sample Clinic',
      siteType: 'clinic',
      siteOdsCode: 'SAM02',
      hours: { days: [0, 1, 2, 3, 4], allDay: false, opens: '08:00', closes: '18:00' },
    });
    expect(response.status).toBe(200);
    const values = (seen.find((call) => call.path === `/fhir/Task/${ID}/$draft`)?.body as { values: Record<string, unknown> }).values;
    expect(values).toEqual({
      fixedSite: true,
      postcode: 'DT4 8XX',
      address: '1 High Street, Dorchester',
      siteName: 'Sample Clinic',
      siteType: 'clinic',
      openingDays: 'mon,tue,wed,thu,fri',
      openingStart: '08:00',
      openingEnd: '18:00',
    });
  });
});
