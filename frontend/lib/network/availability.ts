// Stub for the red commit (TEN-068): no behaviour.
export const offeredNetworks = async (..._args: unknown[]): Promise<{ id: string }[]> => {
  throw new Error('not built');
};
export const requireOffered = async (..._args: unknown[]): Promise<{ id: string }> => {
  throw new Error('not built');
};
