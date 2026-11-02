import { render, screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const state = vi.hoisted(() => ({ session: null as { role: string; roles?: string[] } | null }));

vi.mock('next/navigation', async () => {
  const actual = await vi.importActual<typeof import('next/navigation')>('next/navigation');
  return { ...actual, usePathname: () => '/network-admin' };
});
vi.mock('@/lib/auth/session', () => ({ getSession: async () => state.session }));
vi.mock('@/lib/tenant/profile', () => ({ currentProfile: async () => ({ displayName: 'Sample Lead Organisation' }) }));

import NetworkAdminLayout from './layout';

// The role chip in the network administration header (DEC-1324): a person whose groups give more than one staff
// role can switch from here; with one role it is the plain words, as before.

beforeEach(() => {
  state.session = null;
});

async function layout() {
  return render(await NetworkAdminLayout({ children: <p>The page</p> }));
}

describe('the network administration layout and the role chip', () => {
  it('shows the role as a chip when the session holds more than one', async () => {
    state.session = { role: 'network-admin', roles: ['network-admin', 'lead'] };
    await layout();
    expect(screen.getByText('Network administrator', { selector: 'summary span' })).toBeInTheDocument();
    const menu = screen.getByRole('form', { name: 'Sign in as another role', hidden: true });
    expect(within(menu).getAllByRole('button', { hidden: true }).map((b) => b.getAttribute('value'))).toEqual(['network-admin', 'lead']);
  });

  it('says the plain words for one role, for a session made before the chip, and with no session', async () => {
    state.session = { role: 'network-admin', roles: ['network-admin'] };
    await layout();
    expect(within(screen.getByRole('banner')).getByText('Network administrator')).toBeInTheDocument();
    expect(document.querySelector('details')).toBeNull();
    document.body.innerHTML = '';
    state.session = { role: 'network-admin' };
    await layout();
    expect(document.querySelector('details')).toBeNull();
    document.body.innerHTML = '';
    state.session = null;
    await layout();
    expect(within(screen.getByRole('banner')).getByText('Network administrator')).toBeInTheDocument();
  });
});
