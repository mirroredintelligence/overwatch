import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { operatorSessionFor } from '@/test/operator';
import type { OperatorSession } from '@/lib/operator/session';

let session: OperatorSession | null = null;
vi.mock('@/lib/operator/session', async () => {
  const actual = await vi.importActual<typeof import('@/lib/operator/session')>('@/lib/operator/session');
  return { ...actual, getOperatorSession: async () => session };
});
vi.mock('next/navigation', async () => {
  const actual = await vi.importActual<typeof import('next/navigation')>('next/navigation');
  return { ...actual, usePathname: () => '/operator' };
});

import SignInPage from './sign-in/page';
import AreaLayout from './(area)/layout';
import Home from './(area)/page';
import NewTenant from './(area)/tenants/new/page';
import TenantPage from './(area)/tenants/[id]/page';
import Audit from './(area)/audit/page';
import Support from './(area)/support/page';
import NewSupport from './(area)/support/new/page';
import TicketPage from './(area)/support/tickets/[id]/page';

// The pages of the operator console (TEN-083): each at its own address, each only the component that reads its
// own BFF routes. The role guard is the proxy's (proxy.test.ts) and the BFF's (the routes' tests); a page
// read on its own still says what it is not for.

beforeEach(() => {
  session = operatorSessionFor('platform-operator');
});

describe('/operator/sign-in', () => {
  it('names the console, says who it is for and posts to the console’s own start route', async () => {
    const { container } = render(await SignInPage({ searchParams: Promise.resolve({}) }));
    expect(screen.getByRole('heading', { level: 1, name: 'Platform console' })).toBeInTheDocument();
    expect(screen.getByText('This is for the people who run the platform. Use your platform account.')).toBeInTheDocument();
    const form = container.querySelector('form');
    expect(form).toHaveAttribute('method', 'post');
    expect(form).toHaveAttribute('action', '/api/bff/platform/auth/start');
    expect(screen.getByRole('button', { name: 'Sign in with your platform account' })).toBeInTheDocument();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('says why a sign-in did not work, in the words of the console, and nothing about why', async () => {
    const { unmount } = render(await SignInPage({ searchParams: Promise.resolve({ error: 'no-access' }) }));
    expect(screen.getByText('Your account does not have access to the platform console.')).toBeInTheDocument();
    unmount();
    render(await SignInPage({ searchParams: Promise.resolve({ error: 'failed' }) }));
    expect(screen.getByText('We could not sign you in. Try again.')).toBeInTheDocument();
  });

  it('carries next only when it is a console page, and offers no tenant, directory or role field', async () => {
    const { container, unmount } = render(await SignInPage({ searchParams: Promise.resolve({ next: '/operator/audit' }) }));
    expect(container.querySelector('input[name="next"]')).toHaveAttribute('value', '/operator/audit');
    unmount();
    for (const next of ['/lead', 'https://evil.example', '//evil.example']) {
      const view = render(await SignInPage({ searchParams: Promise.resolve({ next }) }));
      expect(view.container.querySelector('input[name="next"]'), next).toBeNull();
      view.unmount();
    }
    const names = [...render(await SignInPage({ searchParams: Promise.resolve({}) })).container.querySelectorAll('input')].map((i) => i.name);
    expect(names).toEqual([]);
  });
});

describe('the layout', () => {
  it('shows the role’s navigation and the way to sign out, around the page', async () => {
    render(await AreaLayout({ children: <p>page</p> }));
    expect(screen.getByRole('navigation', { name: 'Platform console' })).toBeInTheDocument();
    expect(screen.getByText('Signed in as platform operator')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Sign out' })).toBeInTheDocument();
    expect(screen.getByText('page')).toBeInTheDocument();
  });

  it('says there is no access, and shows no page, when there is no operator session', async () => {
    session = null;
    render(await AreaLayout({ children: <p>page</p> }));
    expect(screen.getByRole('alert')).toHaveTextContent('You do not have access to the platform console.');
    expect(screen.queryByText('page')).not.toBeInTheDocument();
  });
});

describe('the pages', () => {
  it('shows the tenants, the creation, the audit chain and the support requests at their addresses', async () => {
    const cases: [React.ReactElement, string][] = [
      [await Home(), 'Tenants'],
      [<NewTenant key="n" />, 'Create a tenant'],
      [<Audit key="a" />, 'Audit chain'],
    ];
    for (const [page, heading] of cases) {
      const view = render(page);
      expect(await screen.findByRole('heading', { level: 1, name: heading })).toBeInTheDocument();
      view.unmount();
    }
    session = operatorSessionFor('support');
    const view = render(<Support />);
    expect(await screen.findByRole('heading', { level: 1, name: 'Support requests' })).toBeInTheDocument();
    view.unmount();
  });

  it('shows one tenant for an id that is the shape of one, and the page that is not there for any other', async () => {
    render(await TenantPage({ params: Promise.resolve({ id: 'trust-b' }) }));
    expect(await screen.findByRole('heading', { level: 1, name: 'Sample Area B' })).toBeInTheDocument();
    for (const id of ['../x', 'Trust-B', 'a', 'net-1']) await expect(TenantPage({ params: Promise.resolve({ id }) }), id).rejects.toThrow();
  });

  it('shows one request for an id that is the shape of one, and the page that is not there for any other', async () => {
    render(await TicketPage({ params: Promise.resolve({ id: 'tkt-1' }) }));
    expect(await screen.findByRole('heading', { level: 1, name: 'Request tkt-1' })).toBeInTheDocument();
    for (const id of ['../x', 'a b', '']) await expect(TicketPage({ params: Promise.resolve({ id }) }), id).rejects.toThrow();
  });

  it('takes the tenant to ask about from for, only when it is the shape of an id', async () => {
    session = operatorSessionFor('support');
    render(await NewSupport({ searchParams: Promise.resolve({ for: 'trust-a' }) }));
    expect(await screen.findByRole('combobox', { name: 'Tenant' })).toBeInTheDocument();
    expect(await screen.findByRole('option', { name: 'Sample Area A' })).toBeInTheDocument();
  });

  it('says a page read with no operator session is not for the reader', async () => {
    session = null;
    render(await Home());
    expect(screen.getByRole('alert')).toHaveTextContent('You do not have access to the platform console.');
  });
});
