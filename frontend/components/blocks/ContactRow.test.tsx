import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { ContactRow } from './ContactRow';

describe('ContactRow', () => {
  it('shows the label, the value, the status word and an Edit button', () => {
    const onAction = vi.fn();
    const { container } = render(
      <ContactRow kind="phone" label="Coordination phone" value={<>Access team A · <b>01632 960001</b></>} status="done" statusWord="Set" actionLabel="Edit" onAction={onAction} />,
    );
    expect(screen.getByText('Coordination phone')).toBeInTheDocument();
    expect(screen.getByText('01632 960001')).toBeInTheDocument();
    expect(screen.getByText('Set')).toBeInTheDocument();
    expect(container.querySelector('svg[aria-hidden="true"]')).not.toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Edit' }));
    expect(onAction).toHaveBeenCalledTimes(1);
  });

  it('gives the action a name that includes the label when asked', () => {
    render(<ContactRow kind="mail" label="Support email" value="x" status="done" statusWord="Set" actionLabel="Edit" onAction={() => {}} nameAction />);
    expect(screen.getByRole('button', { name: 'Edit Support email' })).toBeInTheDocument();
  });

  it('opens the form in place: children replace the action, the row is marked editing', () => {
    const { container } = render(
      <ContactRow kind="phone" label="Shift lead" value="Staff phone this line." status="todo" statusWord="Not set" editing>
        <label>
          Label
          <input />
        </label>
      </ContactRow>,
    );
    expect(screen.getByLabelText('Label')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Edit|Add/ })).toBeNull();
    expect(container.firstElementChild).toHaveAttribute('data-editing', 'true');
    expect(screen.getByText('Not set')).toBeInTheDocument();
  });

  it('has no axe violations', async () => {
    const { container } = render(<ContactRow kind="mail" label="Support email" value="support@x.example" status="done" statusWord="Set" actionLabel="Edit" onAction={() => {}} />);
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
