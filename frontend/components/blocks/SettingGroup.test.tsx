import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { SettingGroup } from './SettingGroup';

describe('SettingGroup', () => {
  it('shows the title, what it is about and the count, and a closed group hides its content', () => {
    render(
      <SettingGroup open={false} onToggle={() => {}} title="Clinical settings" about="A change needs two approvals from other people." count="3 settings">
        <p>Inside</p>
      </SettingGroup>,
    );
    const head = screen.getByRole('button', { name: /Clinical settings/ });
    expect(head).toHaveAttribute('aria-expanded', 'false');
    expect(screen.getByText('A change needs two approvals from other people.')).toBeInTheDocument();
    expect(screen.getByText('3 settings')).toBeInTheDocument();
    expect(screen.getByText('Inside', { exact: true }).closest('[inert]')).not.toBeNull();
  });

  it('opens and closes through onToggle, and says it is expanded when open', async () => {
    const onToggle = vi.fn();
    const { rerender } = render(
      <SettingGroup open={false} onToggle={onToggle} title="Operational settings" count="2 settings">
        <p>Inside</p>
      </SettingGroup>,
    );
    await userEvent.click(screen.getByRole('button', { name: /Operational settings/ }));
    expect(onToggle).toHaveBeenCalledTimes(1);
    rerender(
      <SettingGroup open onToggle={onToggle} title="Operational settings" count="2 settings">
        <p>Inside</p>
      </SettingGroup>,
    );
    expect(screen.getByRole('button', { name: /Operational settings/ })).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByText('Inside')).toBeVisible();
  });

  it('shows an "n changed" badge in words only when something is changed', () => {
    const { rerender } = render(
      <SettingGroup open onToggle={() => {}} title="Clinical settings" count="3 settings" changed={1}>
        <p>Inside</p>
      </SettingGroup>,
    );
    expect(screen.getByText('1 changed')).toBeInTheDocument();
    rerender(
      <SettingGroup open onToggle={() => {}} title="Clinical settings" count="3 settings" changed={0}>
        <p>Inside</p>
      </SettingGroup>,
    );
    expect(screen.queryByText(/changed/)).not.toBeInTheDocument();
  });

  it('has no accessibility violations', async () => {
    const { container } = render(
      <SettingGroup open onToggle={() => {}} title="Clinical settings" about="About" count="3 settings" changed={2}>
        <p>Inside</p>
      </SettingGroup>,
    );
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
