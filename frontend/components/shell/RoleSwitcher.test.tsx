import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { RoleSwitcher } from './RoleSwitcher';

// The role chip (DEC-1324): the roles the person's groups give, the current one marked, and each choice a button
// that posts the start of a sign-in with that role. The back end decides whether the role is held; this only offers.

function chip(props: Partial<Parameters<typeof RoleSwitcher>[0]> = {}) {
  return render(<RoleSwitcher current="lead" roles={['lead', 'advisor', 'audit']} {...props} />);
}

const menu = () => screen.getByRole('group', { name: 'Sign in as another role', hidden: true });

describe('RoleSwitcher', () => {
  it('shows the current role on the chip and every role in the menu, the current one marked', () => {
    chip();
    expect(screen.getByText('Shift lead', { selector: 'summary span' })).toBeInTheDocument();
    const buttons = within(menu()).getAllByRole('link', { hidden: true });
    expect(buttons.map((b) => b.textContent)).toEqual(['Shift lead', 'Advisor', 'Audit']);
    expect(buttons.map((b) => b.getAttribute('aria-current'))).toEqual(['true', null, null]);
  });

  it('links to the start of a sign-in for the role chosen (a link, so the form-action policy does not limit it)', () => {
    chip();
    const advisor = within(menu()).getByRole('link', { name: 'Advisor', hidden: true });
    expect(advisor).toHaveAttribute('href', '/api/bff/auth/entra/start?role=advisor');
    // No `next`: the person lands on the home of the role chosen.
    expect(advisor.getAttribute('href')).not.toContain('next=');
    expect(menu().querySelector('form')).toBeNull();
  });

  it('uses the words the page gives for a role, and the default words for the rest', () => {
    chip({ words: { lead: 'Shift lead (desk)' } });
    expect(screen.getByText('Shift lead (desk)', { selector: 'summary span' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Advisor', hidden: true })).toBeInTheDocument();
  });

  it('opens from the chip and closes on Escape, returning to the chip', async () => {
    // Enter and Space on a summary open a disclosure in a browser; the test page does not do that, so it clicks.
    const user = userEvent.setup();
    chip();
    const details = document.querySelector('details')!;
    const summary = details.querySelector('summary')!;
    await user.click(summary);
    expect(details).toHaveAttribute('open');
    await user.keyboard('{Escape}');
    expect(details).not.toHaveAttribute('open');
    expect(summary).toHaveFocus();
  });

  it('closes when something else on the page is used', async () => {
    const user = userEvent.setup();
    render(
      <>
        <button type="button">Elsewhere</button>
        <RoleSwitcher current="lead" roles={['lead', 'advisor']} />
      </>,
    );
    const details = document.querySelector('details')!;
    await user.click(details.querySelector('summary')!);
    expect(details).toHaveAttribute('open');
    await user.click(screen.getByRole('button', { name: 'Elsewhere' }));
    expect(details).not.toHaveAttribute('open');
  });

  it('can line the menu up with the left edge, for a chip at the left of a header', () => {
    chip({ align: 'start' });
    expect(menu().className).toMatch(/menuStart/);
  });

  it('has no axe violations closed or open', async () => {
    const user = userEvent.setup();
    const { container } = chip();
    expect(await runAxe(container)).toHaveNoViolations();
    await user.click(container.querySelector('summary')!);
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
