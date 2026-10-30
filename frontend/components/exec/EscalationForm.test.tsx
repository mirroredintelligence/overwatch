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

const LEADERS = [
  { id: 'pr-0101', name: 'Sample Lead One' },
  { id: 'pr-0102', name: 'Sample Lead Two' },
];

describe('EscalationForm with the leadership list (DEC-776)', () => {
  it('offers the leaders by name and saves the id of the one chosen, never a typed id', async () => {
    const onSave = vi.fn();
    render(<EscalationForm initial={initial} busy={false} onSave={onSave} leaders={LEADERS} />);
    expect(screen.queryByRole('textbox', { name: 'Then alert' })).not.toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText('Then alert'), 'Sample Lead Two');
    await userEvent.click(screen.getByRole('button', { name: 'Save' }));
    expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ deputy: 'pr-0102' }));
  });

  it('starts on the saved deputy when they are on the list', () => {
    render(<EscalationForm initial={{ ...initial, deputy: 'pr-0101' }} busy={false} onSave={vi.fn()} leaders={LEADERS} />);
    expect(screen.getByLabelText('Then alert')).toHaveValue('pr-0101');
  });

  it('says the saved deputy is no longer on the list, and saves nothing until another is chosen', async () => {
    const onSave = vi.fn();
    render(<EscalationForm initial={{ ...initial, deputy: 'pr-9999' }} busy={false} onSave={onSave} leaders={LEADERS} />);
    expect(screen.getByText('Your saved deputy is no longer a leader. Choose another.')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Save' }));
    expect(screen.getByText('Enter who to alert next')).toBeInTheDocument();
    expect(onSave).not.toHaveBeenCalled();
  });

  it('says who to choose from is empty, and saves nothing, when the list holds no one', async () => {
    const onSave = vi.fn();
    render(<EscalationForm initial={initial} busy={false} onSave={onSave} leaders={[]} />);
    expect(screen.getByText('No other leader is set up to be your deputy yet. Ask your shift lead.')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Save' }));
    expect(onSave).not.toHaveBeenCalled();
  });

  it('says the list could not be read, and keeps a typed id as the fallback so a person is never locked out', async () => {
    const onSave = vi.fn();
    render(<EscalationForm initial={initial} busy={false} onSave={onSave} leaders={null} />);
    expect(screen.getByText('The list of leaders could not be read.')).toBeInTheDocument();
    expect(screen.getByRole('textbox', { name: 'Then alert' })).toBeInTheDocument();
    await userEvent.type(screen.getByRole('textbox', { name: 'Then alert' }), 'pr-0102');
    await userEvent.click(screen.getByRole('button', { name: 'Save' }));
    expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ deputy: 'pr-0102' }));
  });

  it('has no accessibility violations with the picker', async () => {
    const { container } = render(<EscalationForm initial={initial} busy={false} onSave={vi.fn()} leaders={LEADERS} />);
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
