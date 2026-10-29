import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import SignInPage from './page';

// The sign-in page (W09, artboards AdvisorStart and ClinicalAdvisor step 1).

type Query = Record<string, string | string[] | undefined>;

async function open(query: Query = {}) {
  const view = render(await SignInPage({ searchParams: Promise.resolve(query) }));
  return view;
}

const ACCESS_MESSAGE = 'Your account does not have access to DIUCS capacity. Ask your shift lead to check your access.';

describe('sign-in page copy', () => {
  it('shows the wording from the screen spec', async () => {
    await open();
    expect(screen.getByRole('heading', { level: 1, name: 'DIUCS capacity' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 2, name: 'Sign in' })).toBeInTheDocument();
    expect(screen.getByText('Use your Trust staff account. There is no new password.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Sign in with your Trust account' })).toBeInTheDocument();
    expect(screen.getByText('Having trouble? Ask your shift lead to check your access.')).toBeInTheDocument();
  });

  it('shows the clinical note only with ?role=clinical', async () => {
    const note = 'Clinical advisors see case details, so this uses staff sign-in, not a texted code.';
    const { unmount } = await open({ role: 'clinical' });
    expect(screen.getByText(note)).toBeInTheDocument();
    unmount();
    for (const role of [undefined, 'advisor', 'lead', 'Clinical', 'clinical ', ['clinical', 'lead']]) {
      const view = await open({ role });
      expect(screen.queryByText(note)).not.toBeInTheDocument();
      view.unmount();
    }
  });

  it('shows the access message, as an alert, for ?error=no-access', async () => {
    await open({ error: 'no-access' });
    expect(screen.getByRole('alert')).toHaveTextContent(ACCESS_MESSAGE);
  });

  it('shows a failed sign-in message for ?error=failed, without saying why', async () => {
    await open({ error: 'failed' });
    expect(screen.getByRole('alert')).toHaveTextContent('We could not sign you in. Try again, or ask your shift lead to check your access.');
  });

  it('shows no message for no error, or for an error it does not know, and never echoes it', async () => {
    await open({ error: '<script>alert(1)</script>' });
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(document.body.innerHTML).not.toContain('script>alert');
  });
});

describe('sign-in page form', () => {
  it('posts to the start route with a real button', async () => {
    const { container } = await open();
    const form = container.querySelector('form');
    expect(form).toHaveAttribute('method', 'post');
    expect(form).toHaveAttribute('action', '/api/bff/auth/entra/start');
    const button = within(form as HTMLElement).getByRole('button', { name: 'Sign in with your Trust account' });
    expect(button).toHaveAttribute('type', 'submit');
    expect(button).toHaveAttribute('data-el', 'SIGNIN-ENTRA-BTN');
  });

  it('carries next when it is a same-origin path', async () => {
    const { container } = await open({ next: '/lead?tab=late' });
    expect(container.querySelector('input[name="next"]')).toHaveAttribute('value', '/lead?tab=late');
  });

  it.each(['https://evil.example', '//evil.example', '/\\evil', 'javascript:alert(1)', ['/lead', '/console']])(
    'does not carry next=%j',
    async (next) => {
      const { container } = await open({ next });
      expect(container.querySelector('input[name="next"]')).toBeNull();
    },
  );

  it('has no field that names a tenant, a directory, a role or a hint, whatever the query says', async () => {
    const { container } = await open({ tenant: 'trust-b', tid: 'x', directory: 'y', role: 'clinical', login_hint: 'z', next: '/lead' });
    const names = [...container.querySelectorAll('input, select, textarea')].map((e) => e.getAttribute('name'));
    expect(names).toEqual(['next']);
    expect(container.innerHTML).not.toContain('trust-b');
  });
});

describe('sign-in page accessibility', () => {
  it.each([
    ['plain', {}],
    ['clinical', { role: 'clinical' }],
    ['no access', { error: 'no-access' }],
    ['failed', { error: 'failed' }],
    ['with next', { next: '/lead' }],
  ] as [string, Query][])('has no axe violations (%s)', async (_name, query) => {
    const { container } = await open(query);
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('has a single main landmark', async () => {
    await open();
    expect(screen.getAllByRole('main')).toHaveLength(1);
  });
});
