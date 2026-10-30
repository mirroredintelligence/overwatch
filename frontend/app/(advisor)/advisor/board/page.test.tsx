import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { BOARD_A } from '@/test/fixtures/board';

const session = vi.hoisted(() => ({ value: null as null | { role: string; backendToken: string } }));
const readBoard = vi.hoisted(() => vi.fn());
const redirect = vi.hoisted(() => vi.fn((to: string) => {
  throw new Error(`redirect:${to}`);
}));

vi.mock('@/lib/auth/session', () => ({ getSession: async () => session.value }));
vi.mock('@/lib/board/read', () => ({
  canReadBoard: (role: string) => ['wall', 'advisor', 'lead', 'exec'].includes(role),
  readBoard,
}));
vi.mock('next/navigation', () => ({ redirect }));

import AdvisorBoardPage from './page';

beforeEach(() => {
  session.value = { role: 'advisor', backendToken: 'token-for-advisor' };
  readBoard.mockReset();
  readBoard.mockResolvedValue(BOARD_A);
  redirect.mockClear();
});

describe('advisor wall board view (W10)', () => {
  it('renders the W05 board for the advisor session', async () => {
    render(await AdvisorBoardPage());

    expect(screen.getByRole('heading', { name: 'Dorset urgent care capacity' })).toBeInTheDocument();
    expect(readBoard).toHaveBeenCalledWith(expect.objectContaining({ backendToken: 'token-for-advisor' }));
  });

  it('sends a signed-out visitor to sign in and reads nothing', async () => {
    session.value = null;
    await expect(AdvisorBoardPage()).rejects.toThrow('redirect:/sign-in');
    expect(readBoard).not.toHaveBeenCalled();
  });
});
