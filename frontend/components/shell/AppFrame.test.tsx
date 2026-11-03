import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';

const path = vi.hoisted(() => ({ current: '/admin/users' }));
vi.mock('next/navigation', () => ({ usePathname: () => path.current }));

import { AppFrame, type FrameItem } from './AppFrame';

// The shared frame (design canvas "AppFrame"): a dark rail with the mark, icon-over-label items and Help; a top
// bar with the organisation line, the page title, the role chip and Sign out. Below 900px the rail is a bottom
// bar of at most five entries with the rest under "More".

const ADMIN: readonly FrameItem[] = [
  { label: 'Overview', href: '/admin', icon: 'home', exact: true },
  { label: 'People', href: '/admin/users', icon: 'people' },
  { label: 'Contacts', href: '/admin/contacts', icon: 'mail' },
  { label: 'Settings', href: '/admin/config', icon: 'sliders' },
  { label: 'Retention', href: '/admin/retention', icon: 'db' },
  { label: 'Email', href: '/admin/email', icon: 'send' },
  { label: 'Sharing', href: '/admin/sharing', icon: 'share' },
  { label: 'Access', href: '/admin/access', icon: 'shield' },
  { label: 'Support', href: '/admin/support', icon: 'buoy' },
];

const THREE: readonly FrameItem[] = ADMIN.slice(0, 3);

function frame(props: Partial<React.ComponentProps<typeof AppFrame>> = {}) {
  return render(
    <AppFrame portal="tenant" items={ADMIN} title="People" organisation="Sample Area A" signOut={vi.fn(async () => ({ signedOut: true }))} {...props}>
      <main>
        <h1>The page</h1>
      </main>
    </AppFrame>,
  );
}

function narrow(on: boolean) {
  vi.stubGlobal('matchMedia', (query: string) => ({
    matches: on && query.includes('max-width'),
    media: query,
    addEventListener: () => {},
    removeEventListener: () => {},
  }));
}

beforeEach(() => {
  path.current = '/admin/users';
});
afterEach(() => {
  vi.unstubAllGlobals();
});

describe('AppFrame, wide', () => {
  it('has the mark as the way home, every item with its label, and Help', () => {
    frame({ homeHref: '/admin' });
    expect(screen.getByRole('link', { name: 'Overwatch home' })).toHaveAttribute('href', '/admin');
    const nav = screen.getByRole('navigation', { name: 'Main' });
    expect(within(nav).getAllByRole('link').map((a) => [a.textContent, a.getAttribute('href')])).toEqual(
      ADMIN.map((i) => [i.label, i.href]),
    );
    expect(screen.getByRole('link', { name: 'Help' })).toHaveAttribute('href', '/help');
    expect(document.querySelector('[data-layout]')).toHaveAttribute('data-layout', 'rail');
  });

  it('names the navigation as asked', () => {
    frame({ navLabel: 'Administration' });
    expect(screen.getByRole('navigation', { name: 'Administration' })).toBeInTheDocument();
  });

  it('marks the current page with aria-current, and only that one', () => {
    frame();
    const current = screen.getAllByRole('link', { current: 'page' });
    expect(current.map((a) => a.textContent)).toEqual(['People']);
  });

  it.each([
    ['/admin', 'Overview'],
    ['/admin/', 'Overview'],
    ['/admin/config/3', 'Settings'],
  ])('marks %s as %s', (at, name) => {
    path.current = at;
    frame();
    expect(screen.getAllByRole('link', { current: 'page' }).map((a) => a.textContent)).toEqual([name]);
  });

  it('does not mark an exact item on a page below it, nor a path that only shares a prefix', () => {
    path.current = '/admin/configuration';
    frame();
    expect(screen.queryAllByRole('link', { current: 'page' })).toHaveLength(0);
  });

  it('marks an item for the extra paths it claims', () => {
    path.current = '/operator/tenants/trust-a';
    frame({
      items: [
        { label: 'Organisations', href: '/operator', icon: 'building', exact: true, alsoMatch: ['/operator/tenants'] },
        { label: 'Support', href: '/operator/support', icon: 'buoy' },
      ],
    });
    expect(screen.getAllByRole('link', { current: 'page' }).map((a) => a.textContent)).toEqual(['Organisations']);
  });

  it('draws icons as decoration, so the label is the name', () => {
    frame();
    const nav = screen.getByRole('navigation', { name: 'Main' });
    const svgs = nav.querySelectorAll('svg');
    expect(svgs).toHaveLength(ADMIN.length);
    svgs.forEach((svg) => expect(svg).toHaveAttribute('aria-hidden', 'true'));
    expect(within(nav).getByRole('link', { name: 'People' })).toBeInTheDocument();
  });

  it('has a top bar with the organisation line, the title and Sign out, and holds the page', () => {
    frame();
    const top = screen.getByRole('banner');
    expect(within(top).getByText('Sample Area A')).toBeInTheDocument();
    expect(within(top).getByText('People')).toBeInTheDocument();
    expect(within(top).getByRole('button', { name: 'Sign out' })).toBeInTheDocument();
    expect(screen.getAllByRole('main')).toHaveLength(1);
    expect(screen.getAllByRole('heading')).toHaveLength(1);
  });

  it('takes the title from the current item when none is given', () => {
    path.current = '/admin/contacts';
    frame({ title: undefined });
    expect(within(screen.getByRole('banner')).getByText('Contacts')).toBeInTheDocument();
  });

  it('draws a breadcrumb in the small line, the last step not a link', () => {
    frame({ breadcrumb: [{ label: 'Organisations', href: '/operator' }, { label: 'Trust A' }] });
    const crumbs = screen.getByRole('navigation', { name: 'Breadcrumb' });
    expect(within(crumbs).getByRole('link', { name: 'Organisations' })).toHaveAttribute('href', '/operator');
    expect(within(crumbs).getByText('Trust A')).toHaveAttribute('aria-current', 'page');
  });

  it('signs out through the function it is given', async () => {
    const signOut = vi.fn(async () => ({ signedOut: true }));
    frame({ signOut });
    await userEvent.setup().click(screen.getByRole('button', { name: 'Sign out' }));
    expect(signOut).toHaveBeenCalledTimes(1);
  });

  it('has no Sign out and no navigation when nobody is signed in, but keeps the mark and Help', () => {
    frame({ items: [], showSignOut: false, title: '' });
    expect(screen.queryByRole('button', { name: 'Sign out' })).toBeNull();
    expect(screen.queryByRole('navigation')).toBeNull();
    expect(screen.getByRole('link', { name: 'Overwatch home' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Help' })).toBeInTheDocument();
  });

  it('passes the accessibility checks', async () => {
    const { container } = frame({ role: 'tenant-admin', roles: ['tenant-admin', 'lead'], breadcrumb: [{ label: 'Home', href: '/admin' }, { label: 'People' }] });
    expect(await runAxe(container)).toHaveNoViolations();
  });
});

describe('AppFrame role chip', () => {
  it('is a plain label with one role, none known, or a list that does not hold the role', () => {
    frame({ role: 'tenant-admin', roles: ['tenant-admin'] });
    expect(screen.getByText('Tenant administrator')).toBeInTheDocument();
    expect(document.querySelector('details')).toBeNull();
    document.body.innerHTML = '';
    frame({ role: 'tenant-admin' });
    expect(screen.getByText('Tenant administrator')).toBeInTheDocument();
    expect(document.querySelector('details')).toBeNull();
    document.body.innerHTML = '';
    frame({ role: 'tenant-admin', roles: ['lead', 'advisor'] });
    expect(document.querySelector('details')).toBeNull();
  });

  it('is the role switcher with two or more roles, in the words given', () => {
    frame({ role: 'clinical', roles: ['lead', 'clinical'], roleWords: { lead: 'Shift lead', clinical: 'Clinical advisor' } });
    expect(screen.getByText('Clinical advisor', { selector: 'summary span' })).toBeInTheDocument();
    const menu = screen.getByRole('group', { name: 'Sign in as another role', hidden: true });
    expect(within(menu).getAllByRole('link', { hidden: true }).map((b) => b.textContent)).toEqual(['Shift lead', 'Clinical advisor']);
  });

  it('shows a given word for an operator role as a plain label', () => {
    frame({ portal: 'operator', role: 'platform-operator', roleWords: { 'platform-operator': 'Platform operator' } });
    expect(screen.getByText('Platform operator')).toBeInTheDocument();
    expect(document.querySelector('details')).toBeNull();
  });

  it('shows no role when none is given', () => {
    frame();
    expect(screen.queryByText('Tenant administrator')).toBeNull();
  });
});

describe('AppFrame, narrow', () => {
  it('becomes a bottom bar of five entries at most, the rest under More', async () => {
    narrow(true);
    frame();
    expect(document.querySelector('[data-layout]')).toHaveAttribute('data-layout', 'bar');
    const nav = screen.getByRole('navigation', { name: 'Main' });
    // jsdom lists the links of a closed disclosure too; the entries of the bar itself are the ones outside it.
    const direct = within(nav).getAllByRole('link').filter((a) => !a.closest('details'));
    expect(direct.map((a) => a.textContent)).toEqual(['Overview', 'People', 'Contacts', 'Settings']);
    const more = within(nav).getByText('More', { selector: 'summary span' });
    expect(more).toBeInTheDocument();
    const details = more.closest('details') as HTMLDetailsElement;
    expect(details.open).toBe(false);
    await userEvent.setup().click(more);
    expect(details.open).toBe(true);
    expect(within(details).getAllByRole('link').map((a) => a.textContent)).toEqual([
      'Retention',
      'Email',
      'Sharing',
      'Access',
      'Support',
      'Help',
    ]);
    // Four links, the disclosure: five entries.
    expect(direct.length + 1).toBeLessThanOrEqual(5);
  });

  it('keeps the current page marked inside More, and marks More itself', () => {
    narrow(true);
    path.current = '/admin/support';
    frame();
    const nav = screen.getByRole('navigation', { name: 'Main' });
    expect(within(nav).getByRole('link', { name: 'Support', hidden: true })).toHaveAttribute('aria-current', 'page');
    expect(within(nav).getByText('More', { selector: 'summary span' }).closest('summary')).toHaveAttribute('data-active', 'true');
  });

  it('shows every entry directly when they fit in five, Help last', () => {
    narrow(true);
    frame({ items: THREE });
    const nav = screen.getByRole('navigation', { name: 'Main' });
    expect(within(nav).getAllByRole('link').map((a) => a.textContent)).toEqual(['Overview', 'People', 'Contacts', 'Help']);
    expect(nav.querySelector('details')).toBeNull();
    expect(within(nav).queryByText('More')).toBeNull();
  });

  it('keeps Sign out and the top bar', () => {
    narrow(true);
    frame();
    expect(within(screen.getByRole('banner')).getByRole('button', { name: 'Sign out' })).toBeInTheDocument();
  });

  it('passes the accessibility checks', async () => {
    narrow(true);
    const { container } = frame();
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
