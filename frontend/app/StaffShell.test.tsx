import { render, screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const state = vi.hoisted(() => ({
  session: null as { role: string } | null,
  profile: null as { displayName: string } | null,
  sessionFails: false,
}));

vi.mock('next/navigation', () => ({ usePathname: () => '/clinical' }));
vi.mock('@/lib/auth/session', () => ({
  getSession: async () => {
    if (state.sessionFails) throw new Error('no cookies here');
    return state.session;
  },
}));
vi.mock('@/lib/tenant/profile', () => ({ currentProfile: async () => state.profile }));

import { StaffShell } from './StaffShell';

async function shell() {
  const tree = await StaffShell({ children: <main>content</main> });
  return render(tree);
}

beforeEach(() => {
  state.session = null;
  state.profile = null;
  state.sessionFails = false;
});

describe('StaffShell', () => {
  it('shows the signed-in role and the host organisation', async () => {
    state.session = { role: 'clinical' };
    state.profile = { displayName: 'Dorset system' };
    await shell();
    const header = screen.getByRole('banner');
    expect(within(header).getByText('Clinical advisor')).toBeInTheDocument();
    expect(within(header).getByText('Dorset system')).toBeInTheDocument();
    expect(within(header).getByRole('link', { name: 'Requests' })).toHaveAttribute('href', '/clinical/requests');
    expect(screen.getByText('content')).toBeInTheDocument();
  });

  it('is the logo and Help alone with no session and no profile', async () => {
    await shell();
    const header = screen.getByRole('banner');
    expect(within(header).queryByRole('navigation')).toBeNull();
    expect(within(header).queryByRole('button', { name: 'Sign out' })).toBeNull();
    expect(within(header).getByRole('link', { name: 'Help' })).toBeInTheDocument();
  });

  it('treats a session that cannot be read as no session', async () => {
    state.sessionFails = true;
    await shell();
    expect(screen.queryByRole('button', { name: 'Sign out' })).toBeNull();
  });
});
