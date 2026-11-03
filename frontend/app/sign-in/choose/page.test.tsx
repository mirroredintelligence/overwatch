import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { staffRoleWord } from '@/lib/shell/roleWords';

// The tenant picker (DEC-1327). The choice comes from a sealed cookie; with none the page goes back to
// sign-in. The sealing itself is tested in lib/auth/choice.test.ts (node); here it is unsealed by a stub.

const LISTED = [
  { id: 'fortrus-limited', name: 'Fortrus Limited', roles: ['lead', 'advisor'] },
  { id: 'trust-b', name: 'Trust B', roles: ['advisor'] },
];
vi.mock('@/lib/auth/flow', () => ({
  CHOICE_COOKIE: 'overwatch_choice',
  unsealChoice: async (value: string) => (value === 'a-valid-choice' ? LISTED : null),
}));

const cookieState: { value: string | undefined } = { value: undefined };
vi.mock('next/headers', () => ({
  cookies: async () => ({
    get: (name: string) => (name === 'overwatch_choice' && cookieState.value !== undefined ? { value: cookieState.value } : undefined),
  }),
}));

const redirect = vi.fn((location: string) => {
  throw new Error(`NEXT_REDIRECT ${location}`);
});
vi.mock('next/navigation', () => ({ redirect: (location: string) => redirect(location) }));

import ChoosePage from './page';

beforeEach(() => {
  cookieState.value = undefined;
  redirect.mockClear();
});

describe('the tenant picker', () => {
  it('sends a visitor with no choice back to sign-in', async () => {
    await expect(ChoosePage()).rejects.toThrow('NEXT_REDIRECT /sign-in');
    expect(redirect).toHaveBeenCalledWith('/sign-in');
  });

  it('lists each organisation with its roles, and each choice starts the sign-in for that organisation', async () => {
    cookieState.value = 'a-valid-choice';
    render(await ChoosePage());

    expect(screen.getByRole('heading', { level: 1, name: 'Choose an organisation' })).toBeInTheDocument();
    const choices = screen.getAllByRole('link');
    expect(choices).toHaveLength(2);
    expect(choices[0]).toHaveTextContent('Fortrus Limited');
    expect(choices[0]).toHaveTextContent(`${staffRoleWord('lead')}, ${staffRoleWord('advisor')}`);
    expect(choices[1]).toHaveTextContent('Trust B');

    expect(choices[0]).toHaveAttribute('href', '/api/bff/auth/entra/start?tenant=fortrus-limited');
    expect(choices[1]).toHaveAttribute('href', '/api/bff/auth/entra/start?tenant=trust-b');
  });

  it('sends a visitor whose choice is not ours (a forged or damaged cookie) back to sign-in', async () => {
    cookieState.value = 'not-a-sealed-choice';
    await expect(ChoosePage()).rejects.toThrow('NEXT_REDIRECT /sign-in');
  });
});
