// The reporter posts the back end lists for the lead (GET /lead/reporters, W7B C). The role id is the post's
// own id (not a person's number, and no secret): the lead's remove page picks a post by it (DEC-921). A number
// is only ever its last four digits.

export type ReporterPost = {
  serviceId: string;
  serviceName: string;
  roleId: string;
  role: string;
  channel: string;
  numberEnding: string;
  coveredUntil: string | null;
};

/** A post as the back end gives it. */
export type BackEndPost = ReporterPost;

type Json = Record<string, unknown>;

function isObject(value: unknown): value is Json {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function text(value: unknown): string | null {
  return typeof value === 'string' ? value : null;
}

/**
 * The posts the back end gave. A shape that is not the one the page knows is an error, never an empty list
 * (an empty list would read as "no reporter" when there is one).
 */
export function postsFrom(value: unknown): BackEndPost[] {
  if (!isObject(value) || !Array.isArray(value.reporters)) throw new Error('The reporters could not be read.');
  return value.reporters.map((item) => {
    if (!isObject(item)) throw new Error('The reporters could not be read.');
    const serviceId = text(item.serviceId);
    const serviceName = text(item.serviceName);
    const roleId = text(item.roleId);
    const role = text(item.role);
    const channel = text(item.channel);
    const numberEnding = text(item.numberEnding);
    const coveredUntil = item.coveredUntil === null ? null : text(item.coveredUntil);
    if (serviceId === null || serviceName === null || roleId === null || role === null || channel === null || numberEnding === null || (item.coveredUntil !== null && coveredUntil === null)) {
      throw new Error('The reporters could not be read.');
    }
    return { serviceId, serviceName, roleId, role, channel, numberEnding, coveredUntil };
  });
}

