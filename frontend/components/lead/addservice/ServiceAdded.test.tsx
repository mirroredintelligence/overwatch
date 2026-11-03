import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { ServiceAdded } from './ServiceAdded';

// The state after the service is added (boards/lead/AddService.dc.html): a tick, "<name> is added", what to do
// next. Focus moves to the heading. The existing invite link is the next action.

describe('ServiceAdded', () => {
  it('names the service in its heading and moves focus to it', () => {
    render(<ServiceAdded name="Hospital at home East" serviceId="s-1" onAddAnother={() => undefined} />);
    const heading = screen.getByRole('heading', { level: 1, name: 'Hospital at home East is added' });
    expect(heading).toHaveFocus();
  });

  it('says the service is on the board as not yet reporting', () => {
    render(<ServiceAdded name="X" serviceId="s-1" onAddAnother={() => undefined} />);
    expect(screen.getByText(/It shows on the board as not yet reporting/)).toBeInTheDocument();
  });

  it('links "Invite the reporter" to the invite page for this service', () => {
    render(<ServiceAdded name="X" serviceId="s 1" onAddAnother={() => undefined} />);
    expect(screen.getByRole('link', { name: 'Invite the reporter' })).toHaveAttribute('href', '/lead/reporters/invite?service=s%201');
  });

  it('links to the plain invite page when the answer carried no service id', () => {
    render(<ServiceAdded name="X" serviceId={null} onAddAnother={() => undefined} />);
    expect(screen.getByRole('link', { name: 'Invite the reporter' })).toHaveAttribute('href', '/lead/reporters/invite');
  });

  it('has "Add another service"', async () => {
    const user = userEvent.setup();
    const onAddAnother = vi.fn();
    render(<ServiceAdded name="X" serviceId="s-1" onAddAnother={onAddAnother} />);
    await user.click(screen.getByRole('button', { name: 'Add another service' }));
    expect(onAddAnother).toHaveBeenCalledTimes(1);
  });

  it('has no axe violations', async () => {
    const { container } = render(<ServiceAdded name="X" serviceId="s-1" onAddAnother={() => undefined} />);
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('says the reporter has been texted when the save sent the invitation (DEC-1331)', () => {
    render(<ServiceAdded name="UCR West" serviceId="s-1" invite="sent" onAddAnother={() => {}} />);
    expect(screen.getByText(/has been texted and asked for the capacity figure/)).toBeInTheDocument();
  });

  it('says the text could not be sent when the save could not send it', () => {
    render(<ServiceAdded name="UCR West" serviceId="s-1" invite="failed" onAddAnother={() => {}} />);
    expect(screen.getByText(/could not be sent/)).toBeInTheDocument();
  });
});
