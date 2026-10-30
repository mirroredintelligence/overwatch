import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { resetReporterRequests } from '@/test/msw/handlers/reporter';
import { LockedScreen } from './LockedScreen';

// Full-suite runs share the machine: a PIN or form test clicks many keys, so it gets more time.
vi.setConfig({ testTimeout: 20_000 });

const { push, replace } = vi.hoisted(() => ({ push: vi.fn(), replace: vi.fn() }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ push, replace }) }));

beforeEach(() => {
  push.mockClear();
  replace.mockClear();
  resetReporterRequests();
});

async function typeDigits(digits: string) {
  for (const digit of digits) await userEvent.click(screen.getByRole('button', { name: digit }));
}

describe('LockedScreen', () => {
  it('takes a text code, then a new PIN entered twice, and lands on the app', async () => {
    const { container } = render(<LockedScreen reason={null} />);
    expect(screen.getByRole('heading', { name: 'Your PIN is locked' })).toBeInTheDocument();
    expect(screen.getByText('Nothing was sent or changed.')).toBeInTheDocument();
    expect(await runAxe(container)).toHaveNoViolations();
    await userEvent.click(screen.getByRole('button', { name: 'Text me a code' }));
    const boxes = await screen.findAllByRole('textbox');
    await userEvent.click(boxes[0]);
    await userEvent.paste('482913');
    await userEvent.click(screen.getByRole('button', { name: 'Check code' }));
    expect(await screen.findByRole('heading', { name: 'Create a 6-digit PIN' })).toBeInTheDocument();
    await typeDigits('246810');
    await typeDigits('246810');
    await waitFor(() => expect(push).toHaveBeenCalledWith('/app'));
  });

  it('says Forgot your PIN? and leaves out the five-tries line when reached from the link', () => {
    render(<LockedScreen reason="forgot" />);
    expect(screen.getByRole('heading', { name: 'Forgot your PIN?' })).toBeInTheDocument();
    expect(screen.queryByText(/That was 5 wrong tries/)).toBeNull();
  });
});
