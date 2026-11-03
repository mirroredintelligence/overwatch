import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { CodeInput } from './CodeInput';

function Harness({ onComplete, disabled }: { onComplete?: (code: string) => void; disabled?: boolean }) {
  const [value, setValue] = useState('');
  return <CodeInput value={value} onChange={setValue} onComplete={onComplete} disabled={disabled} dataEl="CODE-INPUT" />;
}

describe('CodeInput', () => {
  it('is ONE numeric one-time-code input named "6-digit code", drawn as six boxes', async () => {
    const { container } = render(<Harness />);
    const inputs = container.querySelectorAll('input');
    expect(inputs).toHaveLength(1);
    const field = screen.getByRole('textbox', { name: '6-digit code' });
    expect(field).toBe(inputs[0]);
    expect(field).toHaveAttribute('inputmode', 'numeric');
    expect(field).toHaveAttribute('autocomplete', 'one-time-code');
    expect(container.querySelectorAll('[data-box]')).toHaveLength(6);
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('shows each typed digit in its own box and says how many are in, never which', async () => {
    const { container } = render(<Harness />);
    await userEvent.type(screen.getByRole('textbox', { name: '6-digit code' }), '482');
    const boxes = [...container.querySelectorAll('[data-box]')];
    expect(boxes.map((box) => box.textContent)).toEqual(['4', '8', '2', '', '', '']);
    expect(boxes.every((box) => box.closest('[aria-hidden="true"]') !== null)).toBe(true);
    expect(screen.getByText('3 digits entered')).toBeInTheDocument();
  });

  it('marks the next box to fill as current', async () => {
    const { container } = render(<Harness />);
    await userEvent.type(screen.getByRole('textbox', { name: '6-digit code' }), '48');
    const boxes = [...container.querySelectorAll('[data-box]')];
    expect(boxes.map((box) => box.getAttribute('data-current'))).toEqual([null, null, 'true', null, null, null]);
  });

  it('fills all six boxes from one paste and reports the complete code once', async () => {
    const complete: string[] = [];
    const { container } = render(<Harness onComplete={(code) => complete.push(code)} />);
    await userEvent.click(screen.getByRole('textbox', { name: '6-digit code' }));
    await userEvent.paste('482 913');
    expect([...container.querySelectorAll('[data-box]')].map((box) => box.textContent)).toEqual(['4', '8', '2', '9', '1', '3']);
    expect(complete).toEqual(['482913']);
  });

  it('keeps only digits and no more than six', async () => {
    render(<Harness />);
    const field = screen.getByRole('textbox', { name: '6-digit code' }) as HTMLInputElement;
    await userEvent.type(field, '4a8-2 91357');
    expect(field.value).toBe('482913');
  });

  it('deletes the last digit on Backspace', async () => {
    render(<Harness />);
    const field = screen.getByRole('textbox', { name: '6-digit code' }) as HTMLInputElement;
    await userEvent.type(field, '48{Backspace}');
    expect(field.value).toBe('4');
  });

  it('is disabled as a whole', () => {
    render(<Harness disabled />);
    expect(screen.getByRole('textbox', { name: '6-digit code' })).toBeDisabled();
  });
});
