import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

vi.mock('next/navigation', async () => {
  const actual = await vi.importActual<typeof import('next/navigation')>('next/navigation');
  return { ...actual, usePathname: () => '/admin/config' };
});
vi.mock('@/lib/tenant/profile', () => ({
  currentProfile: async () => ({ displayName: 'Sample Area A', timeZone: 'Europe/London', locale: 'en-GB', wording: null, coordinationPhone: null, supportSharing: false }),
}));

import AdminLayout from './layout';
import Overview from './page';
import Config from './config/page';
import Version from './config/[n]/page';
import Users from './users/page';
import Access from './access/page';
import Support from './support/page';
import Contacts from './contacts/page';
import Email from './email/page';
import Retention from './retention/page';
import Sharing from './sharing/page';

// The pages of the tenant administration (TEN-076): each at its own address, each only the component that
// reads its own BFF routes. The role guard is the proxy's (proxy.test.ts) and the BFF's (the routes' tests).

describe.each([
  ['/admin', Overview, 'Administration'],
  ['/admin/config', Config, 'Settings'],
  ['/admin/users', Users, 'Users and roles'],
  ['/admin/access', Access, 'Who has accessed your organisation'],
  ['/admin/support', Support, 'Support requests'],
  ['/admin/contacts', Contacts, 'Contacts'],
  ['/admin/email', Email, 'Email sender'],
  ['/admin/retention', Retention, 'Data retention'],
  ['/admin/sharing', Sharing, 'Sharing with the network'],
] as const)('%s', (_path, Page, heading) => {
  it(`shows ${heading}`, async () => {
    render(<Page />);
    expect(await screen.findByRole('heading', { level: 1, name: heading })).toBeInTheDocument();
  });
});

describe('/admin/config/[n]', () => {
  it('shows the version for a whole number', async () => {
    render(await Version({ params: Promise.resolve({ n: '2' }) }));
    expect(await screen.findByRole('heading', { level: 1, name: 'Version 2' })).toBeInTheDocument();
  });

  it.each(['0', '-1', '1.5', 'abc', '1234567', '03'])('is the page that is not there for %s', async (n) => {
    await expect(Version({ params: Promise.resolve({ n }) })).rejects.toThrow();
  });
});

describe('the layout', () => {
  it('shows the organisation’s name, the navigation and the way to sign out', async () => {
    render(await AdminLayout({ children: <p>page</p> }));
    expect(screen.getByText('Sample Area A')).toBeInTheDocument();
    expect(screen.getByRole('navigation', { name: 'Administration' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Sign out' })).toBeInTheDocument();
    expect(screen.getByText('page')).toBeInTheDocument();
  });
});
