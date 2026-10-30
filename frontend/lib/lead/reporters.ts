// The reporter posts the back end lists for the lead (GET /lead/reporters, W7B C). The browser gets each
// post without its role id: the BFF finds the role id itself when it changes a number or removes a person,
// so no internal id is held in the page (DEC-803). A number is only ever its last four digits.

export type ReporterPost = {
  serviceId: string;
  serviceName: string;
  role: string;
  channel: string;
  numberEnding: string;
  coveredUntil: string | null;
};

/** A post as the back end gives it, with the role id the change and remove routes need. */
export type BackEndPost = ReporterPost & { roleId: string };

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

/** The post as the page gets it: no role id. */
export function publicPost({ roleId: _roleId, ...post }: BackEndPost): ReporterPost {
  return post;
}
