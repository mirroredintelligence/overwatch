// Red stubs (DEC-010).
export class InvalidBody extends Error {}
export type ServiceBody = Record<string, unknown>;
export function readServiceBody(value: unknown): ServiceBody {
  void value;
  throw new InvalidBody();
}
export type Parameters = { resourceType: 'Parameters'; parameter: { name: string }[] };
export function toParameters(body: ServiceBody): Parameters {
  void body;
  return { resourceType: 'Parameters', parameter: [] };
}
