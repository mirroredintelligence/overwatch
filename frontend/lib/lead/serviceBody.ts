// Red stubs (DEC-010). The reader returns the body unchanged, so every refusal test fails on its
// assertion, not on a thrown stub (lesson L139).
export class InvalidBody extends Error {}
export type ServiceBody = Record<string, unknown>;
export function readServiceBody(value: unknown): ServiceBody {
  return value as ServiceBody;
}
export type Parameters = { resourceType: 'Parameters'; parameter: { name: string }[] };
export function toParameters(body: ServiceBody): Parameters {
  void body;
  return { resourceType: 'Parameters', parameter: [] };
}
