import { describe, expect, it } from 'vitest';
import { stuckAt, type SetupSteps } from './setupProgress';

const ALL_DONE: SetupSteps = {
  invited: true,
  numberChecked: true,
  channelChosen: true,
  installed: true,
  notificationsOn: true,
  pinSet: true,
  firstReport: true,
};

describe('stuckAt', () => {
  it('names the first step not done, when they are done up to Installed', () => {
    expect(
      stuckAt({ ...ALL_DONE, notificationsOn: false, pinSet: false, firstReport: false }),
    ).toBe('Notifications on');
  });

  it('is null when every step is done', () => {
    expect(stuckAt(ALL_DONE)).toBeNull();
  });

  it('names the first step when nothing after the invitation is done', () => {
    expect(stuckAt({ ...ALL_DONE, numberChecked: false, channelChosen: false, installed: false, notificationsOn: false, pinSet: false, firstReport: false })).toBe('Number checked');
  });
});
