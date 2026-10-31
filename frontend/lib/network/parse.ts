// Stub for the red commit (TEN-068): no behaviour.
export class NetworkParseError extends Error {}
const notBuilt = (): never => {
  throw new NetworkParseError('not built');
};
export const parseNetworks = notBuilt;
export const parseBoard = notBuilt;
export const parseDirectory = notBuilt;
export const parseCriteria = notBuilt;
export const parseSystemNow = notBuilt;
export const parsePhones = notBuilt;
export const parseWeek = notBuilt;
