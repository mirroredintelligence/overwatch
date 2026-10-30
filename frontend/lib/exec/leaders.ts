import { fhirFetch } from '@/lib/fhir/client';

// The leaders a deputy can be chosen from (W39, W7A DEC-776): each an id and a display name, and nothing
// else. The back end sends no phone, email, role or period; this reader keeps none whatever an entry holds.

export type Leader = { id: string; name: string };

type Entry = { resource?: { id?: unknown; name?: { text?: unknown }[] } };

export function leadersFromBundle(body: unknown): Leader[] {
  if (typeof body !== 'object' || body === null || (body as { resourceType?: unknown }).resourceType !== 'Bundle') {
    throw new Error('the back end sent no list of leaders');
  }
  const entries = (body as { entry?: Entry[] }).entry ?? [];
  return entries.flatMap((entry) => {
    const id = entry.resource?.id;
    const name = entry.resource?.name?.[0]?.text;
    return typeof id === 'string' && id !== '' && typeof name === 'string' && name !== '' ? [{ id, name }] : [];
  });
}

/** The leaders as a server page reads them for the set-up and settings screens; null when they cannot be read. */
export async function readLeaders(session: { backendToken: string }): Promise<Leader[] | null> {
  try {
    const { data } = await fhirFetch<unknown>('/Practitioner?role=leadership', { token: session.backendToken });
    return leadersFromBundle(data);
  } catch {
    return null;
  }
}
