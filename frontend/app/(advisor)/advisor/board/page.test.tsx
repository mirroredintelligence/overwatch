import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { FhirError } from '@/lib/fhir/fhirError';
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
vi.mock('next/navigation', () => ({ redirect, useRouter: () => ({ push: vi.fn() }) }));

import AdvisorBoardPage from './page';

beforeEach(() => {
  session.value = { role: 'advisor', backendToken: 'token-for-advisor' };
  readBoard.mockReset();
  readBoard.mockResolvedValue(BOARD_A);
  redirect.mockClear();
});

describe('advisor wall board view (W10)', () => {
  it('renders the board for the advisor session, headed "Board right now"', async () => {
    render(await AdvisorBoardPage());

    expect(screen.getByRole('heading', { level: 1, name: 'Board right now' })).toBeInTheDocument();
    expect(screen.getAllByRole('article')).toHaveLength(9);
    expect(readBoard).toHaveBeenCalledWith(expect.objectContaining({ backendToken: 'token-for-advisor' }));
  });

  it('offers "Start a new call" as the one primary action, and says which board it is', async () => {
    render(await AdvisorBoardPage());

    expect(screen.getByRole('button', { name: 'Start a new call' })).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Which board you are viewing' })).toHaveTextContent('Showing: Our organisation');
  });

  it('draws no "back" link of its own: the frame’s rail is the way home', async () => {
    render(await AdvisorBoardPage());

    expect(screen.queryByRole('link', { name: 'Back to advisor home' })).toBeNull();
  });

  it('sends a signed-out visitor to sign in and reads nothing', async () => {
    session.value = null;
    await expect(AdvisorBoardPage()).rejects.toThrow('redirect:/sign-in');
    expect(readBoard).not.toHaveBeenCalled();
  });

  it('sends a refused read to sign in, and shows no figure when the read fails for any other reason', async () => {
    readBoard.mockRejectedValueOnce(new FhirError(403, { resourceType: 'OperationOutcome', issue: [] }));
    await expect(AdvisorBoardPage()).rejects.toThrow('redirect:/sign-in');

    readBoard.mockRejectedValueOnce(new Error('down'));
    render(await AdvisorBoardPage());
    expect(screen.getByRole('alert')).toHaveTextContent('Board unavailable');
    expect(screen.queryAllByRole('article')).toHaveLength(0);
  });
});
