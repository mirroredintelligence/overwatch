import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { ConfirmDialog } from './ConfirmDialog';

function renderDialog(over: Partial<Parameters<typeof ConfirmDialog>[0]> = {}) {
  const onConfirm = vi.fn();
  const onCancel = vi.fn();
  const utils = render(
    <ConfirmDialog
      title="Remove access for ···0377?"
      confirmLabel="Remove access"
      cancelLabel="Keep access"
      onConfirm={onConfirm}
      onCancel={onCancel}
      {...over}
    >
      The phone will be signed out now. Reason: changed role.
    </ConfirmDialog>,
  );
  return { onConfirm, onCancel, ...utils };
}

describe('ConfirmDialog', () => {
  it('is an alertdialog named by the act and the thing, with the consequence in words', () => {
    renderDialog();
    const dialog = screen.getByRole('alertdialog', { name: 'Remove access for ···0377?' });
    expect(dialog).toHaveAttribute('aria-modal', 'true');
    expect(dialog).toHaveTextContent('The phone will be signed out now. Reason: changed role.');
  });

  it('puts initial focus on the safe choice, not the destructive one', async () => {
    renderDialog();
    await waitFor(() => expect(screen.getByRole('button', { name: 'Keep access' })).toHaveFocus());
    expect(screen.getByRole('button', { name: 'Remove access' })).not.toHaveFocus();
  });

  it('draws both choices at the same size', () => {
    renderDialog();
    const confirm = screen.getByRole('button', { name: 'Remove access' });
    const cancel = screen.getByRole('button', { name: 'Keep access' });
    expect(confirm.className).toBe(cancel.className);
  });

  it('runs onConfirm only from the destructive button', async () => {
    const user = userEvent.setup();
    const { onConfirm, onCancel } = renderDialog();
    await user.click(screen.getByRole('button', { name: 'Remove access' }));
    expect(onConfirm).toHaveBeenCalledTimes(1);
    expect(onCancel).not.toHaveBeenCalled();
  });

  it('cancels from the safe button and from Escape', async () => {
    const user = userEvent.setup();
    const { onConfirm, onCancel } = renderDialog();
    await user.click(screen.getByRole('button', { name: 'Keep access' }));
    expect(onCancel).toHaveBeenCalledTimes(1);
    await user.keyboard('{Escape}');
    expect(onCancel).toHaveBeenCalledTimes(2);
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it('keeps Tab inside the dialog', async () => {
    const user = userEvent.setup();
    renderDialog();
    await waitFor(() => expect(screen.getByRole('button', { name: 'Keep access' })).toHaveFocus());
    await user.tab();
    expect(screen.getByRole('button', { name: 'Remove access' })).toHaveFocus();
    await user.tab();
    expect(screen.getByRole('button', { name: 'Keep access' })).toHaveFocus();
  });

  it('disables only the destructive button while busy', () => {
    renderDialog({ busy: true });
    const confirm = screen.getByRole('button', { name: 'Remove access' });
    expect(confirm).toBeDisabled();
    expect(confirm).toHaveAttribute('aria-busy', 'true');
    expect(screen.getByRole('button', { name: 'Keep access' })).toBeEnabled();
  });

  it('shows an error in words when given one', () => {
    renderDialog({ error: 'Could not remove access. Try again.' });
    expect(screen.getByRole('alert')).toHaveTextContent('Could not remove access. Try again.');
  });

  it('returns focus to the opener on close', async () => {
    const user = userEvent.setup();
    function Harness() {
      const [open, setOpen] = useState(false);
      return (
        <>
          <button type="button" onClick={() => setOpen(true)}>
            Open it
          </button>
          {open ? (
            <ConfirmDialog title="Sure?" confirmLabel="Do it" cancelLabel="Leave it" onConfirm={() => {}} onCancel={() => setOpen(false)}>
              Body.
            </ConfirmDialog>
          ) : null}
        </>
      );
    }
    render(<Harness />);
    await user.click(screen.getByRole('button', { name: 'Open it' }));
    await user.click(screen.getByRole('button', { name: 'Leave it' }));
    expect(screen.getByRole('button', { name: 'Open it' })).toHaveFocus();
  });

  it('has no accessibility violations', async () => {
    const { baseElement } = renderDialog();
    expect(await runAxe(baseElement)).toHaveNoViolations();
  });
});
