// Red-commit stub (DEC-010).
export type ConnectApi = {
  connect: (input: { code: string; name: string; location: string | null }) => Promise<{ name: string; status: 'online'; connectedAt: string }>;
};
export function ScreenForm({ api }: { api?: ConnectApi }) {
  void api;
  return null;
}
