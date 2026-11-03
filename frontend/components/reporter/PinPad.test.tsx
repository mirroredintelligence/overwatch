import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { PinPad } from './PinPad';

describe('PinPad', () => {
  it('announces the count of digits and never shows the digits themselves', async () => {
    const onComplete = vi.fn();
    const { container } = render(<PinPad label="Create a 6-digit PIN" onComplete={onComplete} />);
    await userEvent.click(screen.getByRole('button', { name: '1' }));
    await userEvent.click(screen.getByRole('button', { name: '2' }));
    await userEvent.click(screen.getByRole('button', { name: '3' }));
    expect(screen.getByRole('status')).toHaveTextContent('3 of 6 digits entered');
    expect(screen.getByRole('status').textContent).not.toContain('123');
    // The dots are hidden from assistive technology and hold no digit.
    expect(container.querySelector('[aria-hidden="true"]')?.textContent).toBe('');
    expect(onComplete).not.toHaveBeenCalled();
  });

  it('Delete removes one digit, and the sixth digit completes the PIN once', async () => {
    const onComplete = vi.fn();
    render(<PinPad label="Create a 6-digit PIN" onComplete={onComplete} />);
    for (const digit of ['1', '2', '3', '4', '5']) await userEvent.click(screen.getByRole('button', { name: digit }));
    await userEvent.click(screen.getByRole('button', { name: 'Delete' }));
    expect(screen.getByRole('status')).toHaveTextContent('4 of 6 digits entered');
    for (const digit of ['5', '6']) await userEvent.click(screen.getByRole('button', { name: digit }));
    expect(onComplete).toHaveBeenCalledTimes(1);
    expect(onComplete).toHaveBeenCalledWith('123456');
  });

  it('draws Delete as an icon: named for assistive technology, no visible word', () => {
    render(<PinPad label="Enter your PIN" onComplete={() => undefined} />);
    const del = screen.getByRole('button', { name: 'Delete' });
    expect(del.textContent).toBe('');
    expect(del.querySelector('svg[aria-hidden="true"]')).not.toBeNull();
  });

  it('draws the digits as a hidden-from-AT row of six dots, filled as keys are pressed', async () => {
    const { container } = render(<PinPad label="Enter your PIN" onComplete={() => undefined} dataEl="ONB" />);
    const dots = container.querySelector('[data-el="ONB-DOTS"]') as HTMLElement;
    expect(dots.querySelectorAll('span').length).toBe(6);
    expect(dots.querySelectorAll('[data-filled="true"]').length).toBe(0);
    await userEvent.click(screen.getByRole('button', { name: '4' }));
    await userEvent.click(screen.getByRole('button', { name: '2' }));
    expect(dots.querySelectorAll('[data-filled="true"]').length).toBe(2);
  });

  it('leaves out its own visible label when the page already shows one, and still names the key group', () => {
    render(<PinPad label="Create a 6-digit PIN" showLabel={false} onComplete={() => undefined} />);
    expect(screen.queryByText('Create a 6-digit PIN')).toBeNull();
    expect(screen.getByRole('group', { name: 'Create a 6-digit PIN' })).toBeInTheDocument();
  });

  it('is keyboard-operable with named keys and passes axe', async () => {
    const { container } = render(<PinPad label="Enter your PIN" onComplete={() => undefined} />);
    expect(screen.getAllByRole('button').length).toBe(11);
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
