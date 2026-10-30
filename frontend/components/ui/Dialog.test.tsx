import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { Dialog } from './Dialog';

// The shell handles Escape. Each dialog supplies its own Close and Cancel buttons (W14), so the shell
// draws no button of its own that could share a name with one of them.
function Harness() {
  const [open, setOpen] = useState(false);
  const close = () => setOpen(false);
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>
        Open it
      </button>
      {open ? (
        <Dialog title="Sample dialog" sub="Sub line" dataEl="TEST-DIALOG" onClose={close}>
          <button type="button" onClick={close}>
            Close
          </button>
          <button type="button">First</button>
          <button type="button">Second</button>
        </Dialog>
      ) : null}
    </>
  );
}

describe('Dialog (W14 shell)', () => {
  it('is a modal named by its heading, and moves focus into it', async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(screen.getByRole('button', { name: 'Open it' }));

    const dialog = screen.getByRole('dialog', { name: 'Sample dialog' });
    expect(dialog).toHaveAttribute('aria-modal', 'true');
    expect(dialog).toContainElement(document.activeElement as HTMLElement);
    expect(screen.getByText('Sub line')).toBeInTheDocument();
  });

  it('Escape closes it and returns focus to the button that opened it', async () => {
    const user = userEvent.setup();
    render(<Harness />);
    const opener = screen.getByRole('button', { name: 'Open it' });
    await user.click(opener);

    await user.keyboard('{Escape}');

    expect(screen.queryByRole('dialog')).toBeNull();
    expect(opener).toHaveFocus();
  });

  it('a Close button in the dialog closes it and returns focus', async () => {
    const user = userEvent.setup();
    render(<Harness />);
    const opener = screen.getByRole('button', { name: 'Open it' });
    await user.click(opener);

    await user.click(screen.getByRole('button', { name: 'Close' }));

    expect(screen.queryByRole('dialog')).toBeNull();
    expect(opener).toHaveFocus();
  });

  it('Tab stays inside the dialog: from the last control it returns to the first', async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(screen.getByRole('button', { name: 'Open it' }));
    screen.getByRole('button', { name: 'Second' }).focus();

    await user.tab();

    expect(screen.getByRole('dialog')).toContainElement(document.activeElement as HTMLElement);
    expect(document.activeElement).not.toBe(screen.getByRole('button', { name: 'Open it' }));
  });

  it('has no axe violations when open', async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(screen.getByRole('button', { name: 'Open it' }));
    expect((await runAxe(document.body)).violations).toEqual([]);
  });
});
