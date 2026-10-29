// Telemetry schema (O05). Stub for the red commit: no schemas yet.

export type AttrSpec =
  | { type: 'number' }
  | { type: 'boolean' }
  | { type: 'enum'; values: string[] }
  | { type: 'id'; pattern: RegExp };

export const UI_EVENT_NAMES = [] as const;
export type UiEventName = (typeof UI_EVENT_NAMES)[number];

export const ROLE_VALUES: readonly string[] = [];

export const COMMON_SCHEMA: Record<string, AttrSpec> = {};

export const EVENT_SCHEMAS: Record<UiEventName, Record<string, AttrSpec>> = {} as Record<
  UiEventName,
  Record<string, AttrSpec>
>;

export function isFreeText(_spec: AttrSpec): boolean {
  return false;
}

export function validateEvent(_name: string, _attributes: Record<string, unknown>): string[] {
  return [];
}
