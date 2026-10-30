import { leadRead } from './browser';
import { listOf, textOf } from './answers';

// The services a lead may choose from, read through the BFF (W18 onwards). Any shape that is not the list is
// an error, so a page never offers an empty choice for a failed read.

export type ServiceChoice = { id: string; name: string };

export async function loadServiceChoices(): Promise<ServiceChoice[]> {
  const result = await leadRead('/api/bff/lead/services');
  if (!result.ok) throw new Error('services not read');
  return listOf(result.body, 'services').map((item) => {
    const row = item as Record<string, unknown>;
    return { id: textOf(row.id), name: textOf(row.name) };
  });
}
