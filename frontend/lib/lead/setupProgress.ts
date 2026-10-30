// A reporter's set-up, in the order it happens (W43). The first step not done is where the set-up is stuck.

export const SETUP_STEPS = [
  'invited',
  'numberChecked',
  'channelChosen',
  'installed',
  'notificationsOn',
  'pinSet',
  'firstReport',
] as const;

export type SetupStep = (typeof SETUP_STEPS)[number];
export type SetupSteps = Record<SetupStep, boolean>;

export const STEP_LABEL: Record<SetupStep, string> = {
  invited: 'Invited',
  numberChecked: 'Number checked',
  channelChosen: 'Channel chosen',
  installed: 'Installed',
  notificationsOn: 'Notifications on',
  pinSet: 'PIN set',
  firstReport: 'First report',
};

/** The label of the first step not done, or null when every step is done. */
export function stuckAt(steps: SetupSteps): string | null {
  for (const step of SETUP_STEPS) {
    if (!steps[step]) return STEP_LABEL[step];
  }
  return null;
}
