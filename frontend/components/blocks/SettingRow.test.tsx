import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { SettingRow } from './SettingRow';

const OPTIONS = ['not-updated', 'over-capacity', 'service-closed', 'system-pressure'];

describe('SettingRow', () => {
  it('says "Now X, Default Y" under the label', () => {
    render(<SettingRow label="Clinical take timeout" now="30 minutes" defaultValue="30 minutes" control={{ kind: 'text', value: '30', onChange: () => {} }} />);
    expect(screen.getByText('Clinical take timeout')).toBeInTheDocument();
    expect(screen.getByText(/Now 30 minutes/)).toHaveTextContent('Now 30 minutes · Default 30 minutes');
  });

  it('chips: each option is a toggle button with aria-pressed, and a press reports the new list', async () => {
    const onChange = vi.fn();
    render(
      <SettingRow label="Critical alert kinds" now="service-closed" defaultValue="service-closed" control={{ kind: 'chips', options: OPTIONS, value: ['service-closed'], onChange }} />,
    );
    const on = screen.getByRole('button', { name: /service-closed/ });
    const off = screen.getByRole('button', { name: /over-capacity/ });
    expect(on).toHaveAttribute('aria-pressed', 'true');
    expect(off).toHaveAttribute('aria-pressed', 'false');
    await userEvent.click(off);
    expect(onChange).toHaveBeenLastCalledWith(['service-closed', 'over-capacity']);
    await userEvent.click(on);
    expect(onChange).toHaveBeenLastCalledWith([]);
  });

  it('number: a labelled number field that reports a number, with the unit', async () => {
    const onChange = vi.fn();
    render(<SettingRow label="Re-verify every" now="30 days" defaultValue="30 days" control={{ kind: 'number', value: 30, min: 1, max: 90, unit: 'days', onChange }} />);
    const field = screen.getByRole('spinbutton', { name: 'Re-verify every' });
    expect(field).toHaveValue(30);
    expect(field).toHaveAttribute('min', '1');
    expect(screen.getByText('days')).toBeInTheDocument();
    fireEvent.change(field, { target: { value: '7' } });
    expect(onChange).toHaveBeenLastCalledWith(7);
  });

  it('text: a labelled text field that reports the text', async () => {
    const onChange = vi.fn();
    render(<SettingRow label="System name" now="Overwatch" defaultValue="not set" control={{ kind: 'text', value: '', onChange }} />);
    await userEvent.type(screen.getByRole('textbox', { name: 'System name' }), 'A');
    expect(onChange).toHaveBeenLastCalledWith('A');
  });

  it('offers "Use the default" only when changed, and marks the row changed', async () => {
    const onUseDefault = vi.fn();
    const { container, rerender } = render(
      <SettingRow label="System name" now="X" defaultValue="not set" changed onUseDefault={onUseDefault} control={{ kind: 'text', value: 'X', onChange: () => {} }} />,
    );
    expect(container.firstElementChild).toHaveAttribute('data-changed', 'true');
    await userEvent.click(screen.getByRole('button', { name: 'Use the default for System name' }));
    expect(onUseDefault).toHaveBeenCalledTimes(1);
    rerender(<SettingRow label="System name" now="not set" defaultValue="not set" control={{ kind: 'text', value: '', onChange: () => {} }} />);
    expect(screen.queryByRole('button', { name: /Use the default/ })).not.toBeInTheDocument();
    expect(container.firstElementChild).toHaveAttribute('data-changed', 'false');
  });

  it('a read-only row shows the value as a badge and no control', () => {
    render(<SettingRow label="Alert kinds on by default" now="all kinds" defaultValue="all kinds" />);
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
    expect(screen.getAllByText('all kinds').length).toBeGreaterThan(0);
  });

  it('has no accessibility violations', async () => {
    const { container } = render(
      <div>
        <SettingRow label="Kinds" now="a" defaultValue="a" changed onUseDefault={() => {}} control={{ kind: 'chips', options: OPTIONS, value: ['a'], onChange: () => {} }} />
        <SettingRow label="Days" now="1" defaultValue="1" control={{ kind: 'number', value: 1, onChange: () => {} }} />
        <SettingRow label="Name" now="n" defaultValue="n" control={{ kind: 'text', value: 'n', onChange: () => {} }} />
      </div>,
    );
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
