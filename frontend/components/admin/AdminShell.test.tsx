import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';

let path = '/operator';
vi.mock('next/navigation', () => ({ usePathname: () => path }));

import { AdminShell, isCurrent, navItems } from './AdminShell';

// The frame of the three portals, now on AppFrame: the mark, which portal and organisation, the role, the way
// out and the portal's rail with the current page marked. The page's own main follows it.

beforeEach(() => {
  path = '/operator';
});

function shell(props: Partial<React.ComponentProps<typeof AdminShell>> & { portal: 'operator' | 'tenant' | 'network' }) {
  return render(
    <AdminShell {...props}>
      <main>
        <h1>The page</h1>
      </main>
    </AdminShell>,
  );
}

describe('AdminShell for the platform console', () => {
  it('has the mark as the way home, the console named, the role said in words and a sign-out', () => {
    shell({ portal: 'operator', role: 'platform-operator' });
    expect(screen.getByRole('link', { name: 'Overwatch home' })).toHaveAttribute('href', '/operator');
    const top = screen.getByRole('banner');
    expect(within(top).getByText('Platform console')).toBeInTheDocument();
    expect(within(top).getByText('Platform operator')).toBeInTheDocument();
    expect(within(top).getByRole('button', { name: 'Sign out' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 1, name: 'The page' })).toBeInTheDocument();
    expect(document.querySelector('details')).toBeNull();
  });

  it('gives the operator Organisations and the audit chain, and a support person their requests and Organisations', () => {
    const { unmount } = shell({ portal: 'operator', role: 'platform-operator' });
    const nav = screen.getByRole('navigation', { name: 'Platform console' });
    expect(within(nav).getAllByRole('link').map((a) => [a.textContent, a.getAttribute('href')])).toEqual([
      ['Organisations', '/operator'],
      ['Audit', '/operator/audit'],
    ]);
    unmount();
    shell({ portal: 'operator', role: 'support' });
    expect(within(screen.getByRole('navigation', { name: 'Platform console' })).getAllByRole('link').map((a) => a.textContent)).toEqual(['Support', 'Organisations']);
    expect(within(screen.getByRole('banner')).getByText('Support', { selector: 'span' })).toBeInTheDocument();
  });

  it.each([
    ['/operator', 'Organisations'],
    ['/operator/tenants/new', 'Organisations'],
    ['/operator/tenants/trust-a', 'Organisations'],
    ['/operator/audit', 'Audit'],
  ])('marks %s as the page of %s, and no other', (at, name) => {
    path = at;
    shell({ portal: 'operator', role: 'platform-operator' });
    const current = within(screen.getByRole('navigation', { name: 'Platform console' })).getAllByRole('link').filter((a) => a.getAttribute('aria-current') === 'page');
    expect(current.map((a) => a.textContent)).toEqual([name]);
  });

  it('carries the current page’s name in the top bar', () => {
    path = '/operator/audit';
    shell({ portal: 'operator', role: 'platform-operator' });
    expect(within(screen.getByRole('banner')).getByText('Audit')).toBeInTheDocument();
  });

  it('signs out with the console’s own sign-out when it is given one', async () => {
    const signOut = vi.fn().mockResolvedValue({ signedOut: true });
    shell({ portal: 'operator', role: 'platform-operator', signOut });
    await userEvent.setup().click(screen.getByRole('button', { name: 'Sign out' }));
    expect(signOut).toHaveBeenCalledTimes(1);
  });

  it('has no axe violations', async () => {
    const { container } = shell({ portal: 'operator', role: 'platform-operator' });
    expect(await runAxe(container)).toHaveNoViolations();
  });
});

describe('AdminShell for the tenant administration', () => {
  it('names the organisation, the role and every page of the administration', () => {
    path = '/admin/users';
    shell({ portal: 'tenant', organisation: 'Sample Area A', signOut: vi.fn(), staffRole: 'tenant-admin', staffRoles: ['tenant-admin'] });
    const top = screen.getByRole('banner');
    expect(within(top).getByText('Sample Area A')).toBeInTheDocument();
    expect(within(top).getByText('Tenant administrator')).toBeInTheDocument();
    const nav = screen.getByRole('navigation', { name: 'Administration' });
    expect(within(nav).getAllByRole('link').map((a) => [a.textContent, a.getAttribute('href')])).toEqual([
      ['Overview', '/admin'],
      ['People', '/admin/users'],
      ['Contacts', '/admin/contacts'],
      ['Settings', '/admin/config'],
      ['Retention', '/admin/retention'],
      ['Email', '/admin/email'],
      ['Sharing', '/admin/sharing'],
      ['Access', '/admin/access'],
      ['Support', '/admin/support'],
    ]);
    expect(within(nav).getByRole('link', { name: 'People' })).toHaveAttribute('aria-current', 'page');
    expect(within(nav).getByRole('link', { name: 'Overview' })).not.toHaveAttribute('aria-current');
    expect(screen.getByRole('link', { name: 'Overwatch home' })).toHaveAttribute('href', '/admin');
  });

  it('says the role of the portal when the session does not name one', () => {
    shell({ portal: 'tenant', organisation: 'Sample Area A', signOut: vi.fn() });
    expect(within(screen.getByRole('banner')).getByText('Tenant administrator')).toBeInTheDocument();
  });

  it('says the administration, not an organisation, when the profile is not known', () => {
    shell({ portal: 'tenant', organisation: null, signOut: vi.fn() });
    expect(within(screen.getByRole('banner')).getByText('Administration')).toBeInTheDocument();
  });

  it('shows the role as a chip when the person may switch between roles', () => {
    shell({ portal: 'tenant', organisation: 'Sample Area A', signOut: vi.fn(), staffRole: 'tenant-admin', staffRoles: ['tenant-admin', 'lead'] });
    expect(screen.getByText('Tenant administrator', { selector: 'summary span' })).toBeInTheDocument();
  });
});

describe('AdminShell for the network administration', () => {
  it('names the organisation and the four pages, marking the current one', () => {
    path = '/network-admin/grants';
    shell({ portal: 'network', organisation: 'Sample Area A', signOut: vi.fn() });
    const nav = screen.getByRole('navigation', { name: 'Network administration' });
    expect(within(nav).getAllByRole('link').map((a) => a.textContent)).toEqual(['Members', 'Grants', 'Listings', 'History']);
    expect(within(nav).getByRole('link', { name: 'Grants' })).toHaveAttribute('aria-current', 'page');
    expect(within(screen.getByRole('banner')).getByText('Network administrator')).toBeInTheDocument();
    expect(within(screen.getByRole('banner')).getByText('Sample Area A')).toBeInTheDocument();
  });

  it('has no axe violations', async () => {
    const { container } = shell({ portal: 'network', organisation: 'Sample Area A', signOut: vi.fn() });
    expect(await runAxe(container)).toHaveNoViolations();
  });
});

describe('the navigation helpers', () => {
  it('lists the portal’s own pages only', () => {
    expect(navItems('network').map(([, href]) => href)).toEqual(['/network-admin', '/network-admin/grants', '/network-admin/listings', '/network-admin/history']);
    expect(navItems('tenant')[0]).toEqual(['Overview', '/admin']);
  });

  it('matches a home page to itself only, and a page to itself and its own sub-pages', () => {
    expect(isCurrent('tenant', '/admin/config/3', '/admin')).toBe(false);
    expect(isCurrent('tenant', '/admin/', '/admin')).toBe(true);
    expect(isCurrent('tenant', '/admin/config/3', '/admin/config')).toBe(true);
    expect(isCurrent('tenant', '/admin/configuration', '/admin/config')).toBe(false);
  });
});
