import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { Button } from './Button';

describe('Button disabled', () => {
  it('is disabled without being busy, and a click does nothing', async () => {
    const onClick = vi.fn();
    render(
      <Button variant="primary" disabled onClick={onClick}>
        Choose a number to send
      </Button>,
    );
    const el = screen.getByRole('button', { name: 'Choose a number to send' });
    expect(el).toBeDisabled();
    expect(el).not.toHaveAttribute('aria-busy');
    await userEvent.click(el);
    expect(onClick).not.toHaveBeenCalled();
  });
});
