// Red stubs (DEC-010).
export const SETUP_STEPS = ['invited', 'numberChecked', 'channelChosen', 'installed', 'notificationsOn', 'pinSet', 'firstReport'] as const;
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
export function stuckAt(steps: SetupSteps): string | null {
  void steps;
  return 'wrong';
}
