import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { AuditSearch } from './AuditSearch';

const { push } = vi.hoisted(() => ({ push: vi.fn() }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ push, replace: vi.fn() }) }));

const HINT = "A reference looks like C-48213 or B-20977. It is on the advisor's summary and on the booking.";

describe('AuditSearch', () => {
  it('shows the heading, the reference field with its example, and the Replay it button', () => {
    render(<AuditSearch />);
    expect(screen.getByRole('heading', { name: 'Find a case' })).toBeInTheDocument();
    const input = screen.getByLabelText('Case or booking reference');
    expect(input).toHaveAccessibleDescription(HINT);
    expect(screen.getByText(HINT)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Replay it' })).toBeInTheDocument();
  });

  it('asks for a case or booking reference, and does not navigate without one', async () => {
    push.mockClear();
    const user = userEvent.setup();
    render(<AuditSearch />);
    await user.click(screen.getByRole('button', { name: 'Replay it' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Enter the case or booking reference');
    expect(push).not.toHaveBeenCalled();
  });

  it('marks the reference field invalid while the error shows', async () => {
    const user = userEvent.setup();
    render(<AuditSearch />);
    const input = screen.getByLabelText('Case or booking reference');
    expect(input).toHaveAttribute('aria-invalid', 'false');
    await user.click(screen.getByRole('button', { name: 'Replay it' }));
    await screen.findByRole('alert');
    expect(input).toHaveAttribute('aria-invalid', 'true');
  });

  it('goes to the replay of the reference typed', async () => {
    push.mockClear();
    const user = userEvent.setup();
    render(<AuditSearch />);
    await user.type(screen.getByLabelText('Case or booking reference'), '4821');
    await user.click(screen.getByRole('button', { name: 'Replay it' }));
    expect(push).toHaveBeenCalledWith('/lead/audit/4821');
  });

  it('goes to the replay of a reference in the board form, C-48213', async () => {
    push.mockClear();
    const user = userEvent.setup();
    render(<AuditSearch />);
    await user.type(screen.getByLabelText('Case or booking reference'), 'C-48213');
    await user.click(screen.getByRole('button', { name: 'Replay it' }));
    expect(push).toHaveBeenCalledWith('/lead/audit/C-48213');
  });

  it('submits from the keyboard, with Enter in the field', async () => {
    push.mockClear();
    const user = userEvent.setup();
    render(<AuditSearch />);
    await user.type(screen.getByLabelText('Case or booking reference'), 'B-20977{Enter}');
    expect(push).toHaveBeenCalledWith('/lead/audit/B-20977');
  });

  it('refuses a reference with characters that are not a reference', async () => {
    push.mockClear();
    const user = userEvent.setup();
    render(<AuditSearch />);
    await user.type(screen.getByLabelText('Case or booking reference'), '../admin');
    await user.click(screen.getByRole('button', { name: 'Replay it' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Enter the case or booking reference');
    expect(push).not.toHaveBeenCalled();
  });

  it('has no axe violations', async () => {
    const { container } = render(<AuditSearch />);
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
