// FHIR Parameters for the lead's back-end calls, and the reading of the parts of an answer (W18, W42,
// W43). A part is named, and carries one value of the types the back end reads.

export type ParameterValue =
  | { name: string; valueString: string }
  | { name: string; valueCode: string }
  | { name: string; valueInteger: number }
  | { name: string; valueDate: string }
  | { name: string; valueDateTime: string }
  | { name: string; valueBoolean: boolean };

export type Parameters = { resourceType: 'Parameters'; parameter: ParameterValue[] };

export function parametersOf(parts: ParameterValue[]): Parameters {
  return { resourceType: 'Parameters', parameter: parts };
}

/** The first value of a named part of an answer, or undefined. Only the value types above are read. */
export function partValue(resource: unknown, name: string): unknown {
  const parts = (resource as { parameter?: unknown } | undefined)?.parameter;
  if (!Array.isArray(parts)) return undefined;
  const part = parts.find((item) => (item as { name?: unknown }).name === name) as Record<string, unknown> | undefined;
  if (!part) return undefined;
  for (const key of ['valueString', 'valueCode', 'valueInteger', 'valueBoolean', 'valueDateTime', 'valueDate']) {
    if (key in part) return part[key];
  }
  return undefined;
}
