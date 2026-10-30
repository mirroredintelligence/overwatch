import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { DEFAULT_ALERT_PREFERENCES } from '@/lib/exec/alertPrefs';
import { runAxe } from '@/test/a11y';
import { EscalationForm } from './EscalationForm';

const initial = { ...DEFAULT_ALERT_PREFERENCES, deputy: '' };

describe('EscalationForm', () => {
  it('hides the critical-only choice when quiet hours are None', async () => {
    render(<EscalationForm initial={initial} busy={false} onSave={vi.fn()} />);
    await userEvent.click(screen.getByRole('button', { name: 'None' }));
    expect(screen.queryByRole('button', { name: 'Critical only' })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: '22:00 to 06:00' }));
    expect(screen.getByRole('button', { name: 'Critical only' })).toBeInTheDocument();
  });

  it('shows "Enter who to alert next" when the deputy is empty, and saves nothing', async () => {
    const onSave = vi.fn();
    render(<EscalationForm initial={initial} busy={false} onSave={onSave} />);
    await userEvent.click(screen.getByRole('button', { name: 'Save' }));
    expect(screen.getByText('Enter who to alert next')).toBeInTheDocument();
    expect(onSave).not.toHaveBeenCalled();
  });

  it('saves the chosen window and deputy', async () => {
    const onSave = vi.fn();
    render(<EscalationForm initial={initial} busy={false} onSave={onSave} />);
    await userEvent.click(screen.getByRole('button', { name: '15 min' }));
    await userEvent.type(screen.getByLabelText('Then alert'), 'pr-0042');
    await userEvent.click(screen.getByRole('button', { name: 'Save' }));
    expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ ackMinutes: 15, deputy: 'pr-0042' }));
  });

  it('has no accessibility violations', async () => {
    const { container } = render(<EscalationForm initial={initial} busy={false} onSave={vi.fn()} />);
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
