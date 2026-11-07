// The invitations and their set-up steps (GET /lead/invitations, W7B C), checked before the page gets them. A
// step that is not a yes or no is an error: a missing step would read as "not done" and send the lead to phone a
// reporter who is set up.

import { SETUP_STEPS, type SetupSteps } from './setupProgress';

export type InvitationRow = {
  id: string;
  serviceId: string;
  serviceName: string;
  role: string;
  // The invited person's own name; null when none is stored or it is only the role label.
  inviteeName: string | null;
  steps: SetupSteps;
  invitedAt: string;
  lastSeen: string;
  firstReportAt: string | null;
};

// "Dee Lead - Service lead", or just the role label when no name is stored. Never a number.
export function invitedAs(item: { role: string; inviteeName?: string | null }): string {
  const name = item.inviteeName?.trim();
  return name && name.toLowerCase() !== item.role.trim().toLowerCase() ? `${name} - ${item.role}` : item.role;
}

type Json = Record<string, unknown>;

function isObject(value: unknown): value is Json {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

const bad = () => new Error('The invitations could not be read.');

export function invitationsFrom(value: unknown): InvitationRow[] {
  if (!isObject(value) || !Array.isArray(value.items)) throw bad();
  return value.items.map((item) => {
    if (!isObject(item) || !isObject(item.steps)) throw bad();
    const steps = {} as SetupSteps;
    for (const step of SETUP_STEPS) {
      const done = (item.steps as Json)[step];
      if (typeof done !== 'boolean') throw bad();
      steps[step] = done;
    }
    const { id, serviceId, serviceName, role, invitedAt, lastSeen, firstReportAt, inviteeName } =
      item;
    if (
      typeof id !== 'string' ||
      typeof serviceId !== 'string' ||
      typeof serviceName !== 'string' ||
      typeof role !== 'string' ||
      (inviteeName !== null && inviteeName !== undefined && typeof inviteeName !== 'string') ||
      typeof invitedAt !== 'string' ||
      typeof lastSeen !== 'string' ||
      (firstReportAt !== null && typeof firstReportAt !== 'string' && firstReportAt !== undefined)
    ) {
      throw bad();
    }
    return {
      id,
      serviceId,
      serviceName,
      role,
      inviteeName: typeof inviteeName === 'string' && inviteeName.trim() ? inviteeName : null,
      steps,
      invitedAt,
      lastSeen,
      firstReportAt: typeof firstReportAt === 'string' ? firstReportAt : null,
    };
  });
}
