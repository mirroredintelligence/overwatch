import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { CriteriaHistory } from './CriteriaHistory';

const { push } = vi.hoisted(() => ({ push: vi.fn() }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ push, replace: vi.fn() }) }));

// The user-event tests here run slowly when the whole suite shares the machine; the budget is per file.
vi.setConfig({ testTimeout: 15_000 });

describe('CriteriaHistory', () => {
  it('lists the versions newest first, marks the waiting one, and offers a new draft from version 3', async () => {
    const { container } = render(<CriteriaHistory serviceId="s1" />);
    expect(await screen.findByRole('heading', { level: 1, name: 'History' })).toBeInTheDocument();
    const items = screen.getAllByRole('listitem');
    expect(items.map((item) => item.textContent)).toEqual([
      'Version 4Waiting',
      expect.stringContaining('Version 3'),
      expect.stringContaining('Version 2'),
      'Version 1At registration',
    ]);
    expect(within(items[0]!).getByText('Waiting')).toBeInTheDocument();
    expect(screen.getByText('Every version stays in the audit record.')).toBeInTheDocument();
    const draft = screen.getByRole('button', { name: 'Start a new draft from version 3' });
    expect(draft).toHaveAttribute('data-el', 'OWN-HISTORY-NEWDRAFT-BTN');
    await userEvent.setup().click(draft);
    expect(push).toHaveBeenCalledWith('/criteria/s1?step=edit');
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
