import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

vi.mock('next/navigation', async () => {
  const actual = await vi.importActual<typeof import('next/navigation')>('next/navigation');
  return { ...actual, usePathname: () => '/network-admin/grants' };
});
vi.mock('@/lib/tenant/profile', () => ({
  currentProfile: async () => ({ displayName: 'Sample Lead Organisation', timeZone: 'Europe/London', locale: 'en-GB', wording: null, coordinationPhone: null, supportSharing: false }),
}));

import { metadata as grantsMetadata } from './grants/page';
import { metadata as historyMetadata } from './history/page';
import { metadata as listingsMetadata } from './listings/page';
import { metadata as membersMetadata } from './page';
import NetworkAdminLayout from './layout';
import History from './history/page';
import Grants from './grants/page';
import Listings from './listings/page';
import Members from './page';

// The pages of the network administration (TEN-080): each at its own address, each only the component that
// reads its own BFF routes. The role guard is the proxy's (proxy.test.ts) and the BFF's (the routes' tests).

describe.each([
  ['/network-admin', Members, 'Network members'],
  ['/network-admin/grants', Grants, 'Grants'],
  ['/network-admin/listings', Listings, 'Listings'],
  ['/network-admin/history', History, 'History'],
] as const)('%s', (_path, Page, heading) => {
  it(`shows ${heading}`, async () => {
    render(<Page />);
    expect(await screen.findByRole('heading', { level: 1, name: heading })).toBeInTheDocument();
  });
});

describe('the metadata', () => {
  it('names each page by its own title and keeps it out of search', () => {
    expect([membersMetadata, grantsMetadata, listingsMetadata, historyMetadata].map((m) => [m.title, m.robots])).toEqual([
      ['Network members', { index: false }],
      ['Grants', { index: false }],
      ['Listings', { index: false }],
      ['History', { index: false }],
    ]);
  });
});

describe('the layout', () => {
  it('puts the organisation’s own name first, then the navigation, the page and the way to sign out', async () => {
    render(await NetworkAdminLayout({ children: <p>The page</p> }));
    expect(screen.getByText('Sample Lead Organisation')).toBeInTheDocument();
    expect(screen.getByRole('navigation', { name: 'Network administration' })).toBeInTheDocument();
    expect(screen.getByText('The page')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /sign out/i })).toBeInTheDocument();
  });
});
