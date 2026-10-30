import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { AuditSearch } from './AuditSearch';

const { push } = vi.hoisted(() => ({ push: vi.fn() }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ push, replace: vi.fn() }) }));

describe('AuditSearch', () => {
  it('asks for a case or booking reference, and does not navigate without one', async () => {
    push.mockClear();
    const user = userEvent.setup();
    render(<AuditSearch />);
    await user.click(screen.getByRole('button', { name: 'Find' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Enter the case or booking reference');
    expect(push).not.toHaveBeenCalled();
  });

  it('goes to the replay of the reference typed', async () => {
    push.mockClear();
    const user = userEvent.setup();
    render(<AuditSearch />);
    await user.type(screen.getByLabelText('Case or booking reference'), '4821');
    await user.click(screen.getByRole('button', { name: 'Find' }));
    expect(push).toHaveBeenCalledWith('/lead/audit/4821');
  });

  it('refuses a reference with characters that are not a reference', async () => {
    push.mockClear();
    const user = userEvent.setup();
    render(<AuditSearch />);
    await user.type(screen.getByLabelText('Case or booking reference'), '../admin');
    await user.click(screen.getByRole('button', { name: 'Find' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Enter the case or booking reference');
    expect(push).not.toHaveBeenCalled();
  });

  it('has no axe violations', async () => {
    const { container } = render(<AuditSearch />);
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
