import { fhirFetch } from '@/lib/fhir/client';

// Server-only. The back end calls behind a service card's dialogs (W14): the criteria history, and the
// two advisor answers about a service. The case is named by its id in the body of the answer.

/** The criteria history of a service (GET /fhir/Basic?subject=HealthcareService/{id}). */
export async function readCriteriaHistory(token: string, serviceId: string): Promise<unknown> {
  const { data } = await fhirFetch<unknown>(
    `/Basic?subject=${encodeURIComponent(`HealthcareService/${serviceId}`)}`,
    { token },
  );
  return data;
}

export type Said = 'accepting' | 'limited' | 'not-accepting';
export type DeclineReason = 'full' | 'outside-criteria' | 'staffing-or-transport' | 'other';

/** "I phoned": what the service said on the phone (R07 $advisor-phoned). */
export async function postAdvisorPhoned(
  token: string,
  serviceId: string,
  caseId: string,
  said: Said,
  value: number,
  idempotencyKey: string,
): Promise<void> {
  await fhirFetch<unknown>(`/HealthcareService/${encodeURIComponent(serviceId)}/$advisor-phoned`, {
    method: 'POST',
    token,
    idempotencyKey,
    body: {
      resourceType: 'Parameters',
      parameter: [
        { name: 'case', valueReference: { reference: `ServiceRequest/${caseId}` } },
        { name: 'status', valueCode: said },
        { name: 'value', valueInteger: value },
      ],
    },
  });
}

/** "They declined": the service declined although the board showed capacity (R07 $declined). */
export async function postDeclined(
  token: string,
  serviceId: string,
  caseId: string,
  reason: DeclineReason,
  idempotencyKey: string,
): Promise<void> {
  await fhirFetch<unknown>(`/HealthcareService/${encodeURIComponent(serviceId)}/$declined`, {
    method: 'POST',
    token,
    idempotencyKey,
    body: {
      resourceType: 'Parameters',
      parameter: [
        { name: 'case', valueReference: { reference: `ServiceRequest/${caseId}` } },
        { name: 'reason', valueCode: reason },
      ],
    },
  });
}
