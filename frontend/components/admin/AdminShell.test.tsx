import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';

let path = '/operator';
vi.mock('next/navigation', () => ({ usePathname: () => path }));

import { AdminShell, isCurrent, navItems } from './AdminShell';

// The frame of the three portals: the logo, which portal and organisation, who is signed in, the way out and
// the portal's navigation with the current page marked. The page's own main follows it.

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
  it('has the logo as the way home, the console named, the role said in words and a sign-out', () => {
    shell({ portal: 'operator', role: 'platform-operator' });
    expect(screen.getByRole('link', { name: 'Overwatch' })).toHaveAttribute('href', '/operator');
    expect(screen.getByText('Platform console', { selector: 'span' })).toBeInTheDocument();
    expect(screen.getByText(/Signed in as/)).toHaveTextContent('Signed in as platform operator');
    expect(screen.getByRole('button', { name: 'Sign out' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 1, name: 'The page' })).toBeInTheDocument();
  });

  it('gives the operator Tenants and the audit chain, and a support person their requests and Tenants', () => {
    const { unmount } = shell({ portal: 'operator', role: 'platform-operator' });
    const nav = screen.getByRole('navigation', { name: 'Platform console' });
    expect(within(nav).getAllByRole('link').map((a) => [a.textContent, a.getAttribute('href')])).toEqual([
      ['Tenants', '/operator'],
      ['Audit chain', '/operator/audit'],
    ]);
    unmount();
    shell({ portal: 'operator', role: 'support' });
    expect(within(screen.getByRole('navigation', { name: 'Platform console' })).getAllByRole('link').map((a) => a.textContent)).toEqual(['Support requests', 'Tenants']);
    expect(screen.getByText(/Signed in as/)).toHaveTextContent('Signed in as support');
  });

  it.each([
    ['/operator', 'Tenants'],
    ['/operator/tenants/new', 'Tenants'],
    ['/operator/tenants/trust-a', 'Tenants'],
    ['/operator/audit', 'Audit chain'],
  ])('marks %s as the page of %s, and no other', (at, name) => {
    path = at;
    shell({ portal: 'operator', role: 'platform-operator' });
    const current = within(screen.getByRole('navigation', { name: 'Platform console' })).getAllByRole('link').filter((a) => a.getAttribute('aria-current') === 'page');
    expect(current.map((a) => a.textContent)).toEqual([name]);
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
    shell({ portal: 'tenant', organisation: 'Sample Area A', signOut: vi.fn() });
    expect(screen.getByText('Sample Area A')).toBeInTheDocument();
    expect(screen.getByText(/Signed in as/)).toHaveTextContent('Signed in as tenant administrator');
    const nav = screen.getByRole('navigation', { name: 'Administration' });
    expect(within(nav).getAllByRole('link')).toHaveLength(9);
    expect(within(nav).getByRole('link', { name: 'Users and roles' })).toHaveAttribute('aria-current', 'page');
    expect(within(nav).getByRole('link', { name: 'Overview' })).not.toHaveAttribute('aria-current');
    expect(screen.getByRole('link', { name: 'Overwatch' })).toHaveAttribute('href', '/admin');
  });

  it('says the administration, not an organisation, when the profile is not known', () => {
    shell({ portal: 'tenant', organisation: null, signOut: vi.fn() });
    expect(screen.getByText('Administration', { selector: 'span' })).toBeInTheDocument();
  });
});

describe('AdminShell for the network administration', () => {
  it('names the organisation and the four pages, marking the current one', () => {
    path = '/network-admin/grants';
    shell({ portal: 'network', organisation: 'Sample Area A', signOut: vi.fn() });
    const nav = screen.getByRole('navigation', { name: 'Network administration' });
    expect(within(nav).getAllByRole('link').map((a) => a.textContent)).toEqual(['Members', 'Grants', 'Listings', 'History']);
    expect(within(nav).getByRole('link', { name: 'Grants' })).toHaveAttribute('aria-current', 'page');
    expect(screen.getByText(/Signed in as/)).toHaveTextContent('Signed in as network administrator');
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
