// Red stubs (DEC-010).
export type FlagItem = { id: string; serviceId: string; serviceName: string; reason: string; summary: string };
export function flagSummary(reason: string): string {
  void reason;
  return '';
}
export function flagItemsFrom(bundle: unknown): FlagItem[] {
  void bundle;
  return [];
}
