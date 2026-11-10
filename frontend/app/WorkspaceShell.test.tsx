import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { useWorkspace, type WorkspaceValue } from '@/components/workspace/WorkspaceProvider';

// The workspace shell (DEC-1376, WS-SHL): the same reads as StaffShell (session and profile) without the rail, handing
// the provider the role, the roles and the organisation. A failed read is the same as none.

const state = vi.hoisted(() => ({
  session: null as { role: string; roles?: string[] } | null,
  profile: null as { displayName: string } | null,
  sessionFails: false,
}));

vi.mock('@/lib/auth/session', () => ({
  getSession: async () => {
    if (state.sessionFails) throw new Error('no cookies here');
    return state.session;
  },
}));
vi.mock('@/lib/tenant/profile', () => ({ currentProfile: async () => state.profile }));

import { WorkspaceShell } from './WorkspaceShell';

// Reports the identity the provider hands to a child, so a test can read what the shell built.
type Identity = WorkspaceValue['identity'];
function Probe({ report }: { report: (identity: Identity) => void }) {
  report(useWorkspace().identity);
  return null;
}

async function shell(report: (identity: Identity) => void) {
  const tree = await WorkspaceShell({ children: <Probe report={report} /> });
  return render(tree);
}

beforeEach(() => {
  state.session = null;
  state.profile = null;
  state.sessionFails = false;
});

describe('WorkspaceShell', () => {
  it('WS-SHL-T01 renders its children inside the provider with the session role, its roles and the organisation', async () => {
    state.session = { role: 'advisor-v2' };
    state.profile = { displayName: 'Test Organisation' };
    const report = vi.fn<(identity: Identity) => void>();
    await shell(report);
    expect(report).toHaveBeenLastCalledWith({
      role: 'advisor-v2',
      roles: ['advisor-v2'],
      organisation: 'Test Organisation',
    });
  });

  it('WS-SHL-T02 with no session (the read rejects) the role is null and the organisation still comes from the profile; with no profile it is null', async () => {
    state.sessionFails = true;
    state.profile = { displayName: 'Test Organisation' };
    const failed = vi.fn<(identity: Identity) => void>();
    await shell(failed);
    expect(failed).toHaveBeenLastCalledWith(expect.objectContaining({ role: null, organisation: 'Test Organisation' }));

    document.body.innerHTML = '';
    state.sessionFails = false;
    state.session = null;
    state.profile = null;
    const empty = vi.fn<(identity: Identity) => void>();
    await shell(empty);
    expect(empty).toHaveBeenLastCalledWith(expect.objectContaining({ role: null, organisation: null }));
    expect(screen.queryByRole('navigation')).toBeNull();
  });
});
