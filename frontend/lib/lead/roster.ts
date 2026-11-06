// The duty roster of a service as the page reads it (DEC-1341). Pure. A person is on shift, off shift, or (never
// listed) removed. The number is its last four digits only.

export type RosterState = 'on-shift' | 'off-shift';

export type RosterManager = {
  roleId: string;
  name: string;
  /** The last four digits of the number, or null when none is held. */
  numberEnding: string | null;
  state: RosterState;
  /** When the shift ends, as an instant, for a person on shift. */
  shiftEnd: string | null;
};

export type Roster = { managers: RosterManager[] };

export class RosterParseError extends Error {
  constructor() {
    super('The roster is not in the shape the page knows.');
    this.name = 'RosterParseError';
  }
}

const isObject = (value: unknown): value is Record<string, unknown> => typeof value === 'object' && value !== null && !Array.isArray(value);

export function parseRoster(value: unknown): Roster {
  if (!isObject(value) || !Array.isArray(value.managers)) throw new RosterParseError();
  return {
    managers: value.managers.map((item) => {
      if (!isObject(item)) throw new RosterParseError();
      const { roleId, name, numberEnding, state, shiftEnd } = item;
      if (typeof roleId !== 'string' || typeof name !== 'string') throw new RosterParseError();
      if (state !== 'on-shift' && state !== 'off-shift') throw new RosterParseError();
      if (numberEnding !== null && typeof numberEnding !== 'string') throw new RosterParseError();
      if (shiftEnd !== null && (typeof shiftEnd !== 'string' || Number.isNaN(Date.parse(shiftEnd)))) throw new RosterParseError();
      return { roleId, name, numberEnding, state, shiftEnd };
    }),
  };
}

/** What the page says of a person's shift, in words. */
export function shiftWords(manager: RosterManager, clockText: (iso: string) => string): string {
  return manager.state === 'on-shift' && manager.shiftEnd !== null ? `On shift until ${clockText(manager.shiftEnd)}` : 'Off shift';
}
