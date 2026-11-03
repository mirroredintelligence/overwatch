import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { InvitePreview } from './InvitePreview';

// The text bubble beside the invite form (INV-02): a polite live region, with a Show text disclosure on a phone.

describe('InvitePreview', () => {
  it('shows the text the reporter gets, in a labelled region', () => {
    render(<InvitePreview service="UCR West" />);
    const region = screen.getByRole('complementary', { name: 'The text we send' });
    expect(region).toHaveTextContent('The text they get');
    expect(region).toHaveTextContent(
      'Overwatch: you are invited to report capacity for UCR West. Setting up takes about 3 minutes: [link to set up]. The link works for 48 hours.',
    );
  });

  it('says this service until one is chosen', () => {
    render(<InvitePreview service="" />);
    expect(screen.getByText(/report capacity for this service\./)).toBeInTheDocument();
  });

  it('puts the bubble in a polite live region', () => {
    render(<InvitePreview service="UCR West" />);
    const live = screen.getByRole('status');
    expect(live).toHaveAttribute('aria-live', 'polite');
    expect(live).toHaveTextContent(/UCR West/);
  });

  it('says the link is made on send, and that only pilot services can be invited', () => {
    render(<InvitePreview service="UCR West" />);
    expect(screen.getByText(/The link is made when you send\./)).toBeInTheDocument();
    expect(screen.getByText('Only services in the pilot')).toBeInTheDocument();
  });

  it('has a Show text disclosure that opens and closes the full text', async () => {
    const user = userEvent.setup();
    render(<InvitePreview service="UCR West" />);
    const toggle = screen.getByRole('button', { name: 'Show text' });
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    await user.click(toggle);
    expect(screen.getByRole('button', { name: 'Hide text' })).toHaveAttribute('aria-expanded', 'true');
    await user.click(screen.getByRole('button', { name: 'Hide text' }));
    expect(screen.getByRole('button', { name: 'Show text' })).toHaveAttribute('aria-expanded', 'false');
  });

  it('has no axe violations', async () => {
    const { container } = render(<InvitePreview service="UCR West" />);
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
