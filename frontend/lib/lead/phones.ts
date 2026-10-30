// The phones the lead's services report from (GET /lead/phones, W7B C), checked before the page gets them.
// A phone is its last digits (phoneEnding), never the whole number.

export type PhoneRow = {
  phoneEnding: string;
  role: string;
  services: { id: string; name: string }[];
  channel: string | null;
  lastSeen: string | null;
};

type Json = Record<string, unknown>;

function isObject(value: unknown): value is Json {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

const bad = () => new Error('The phones could not be read.');

export function phonesFrom(value: unknown): PhoneRow[] {
  if (!isObject(value) || !Array.isArray(value.phones)) throw bad();
  return value.phones.map((item) => {
    if (!isObject(item) || typeof item.phoneEnding !== 'string' || typeof item.role !== 'string' || !Array.isArray(item.services)) {
      throw bad();
    }
    const services = item.services.map((service) => {
      if (!isObject(service) || typeof service.id !== 'string' || typeof service.name !== 'string') throw bad();
      return { id: service.id, name: service.name };
    });
    const channel = item.channel === null ? null : typeof item.channel === 'string' ? item.channel : undefined;
    const lastSeen = item.lastSeen === null ? null : typeof item.lastSeen === 'string' ? item.lastSeen : undefined;
    if (channel === undefined || lastSeen === undefined) throw bad();
    return { phoneEnding: item.phoneEnding, role: item.role, services, channel, lastSeen };
  });
}
