import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { CodeInput } from './CodeInput';

function Harness({ onComplete }: { onComplete?: (code: string) => void }) {
  const [value, setValue] = useState('');
  return <CodeInput value={value} onChange={setValue} onComplete={onComplete} />;
}

describe('CodeInput', () => {
  it('is one group with the label "6-digit code" and six single-digit boxes', async () => {
    const { container } = render(<Harness />);
    const group = screen.getByRole('group', { name: '6-digit code' });
    expect(group.querySelectorAll('input')).toHaveLength(6);
    for (const box of group.querySelectorAll('input')) {
      expect(box).toHaveAttribute('inputmode', 'numeric');
    }
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('fills all six boxes from one paste and reports the complete code', async () => {
    const complete: string[] = [];
    render(<Harness onComplete={(code) => complete.push(code)} />);
    const first = screen.getAllByRole('textbox')[0];
    await userEvent.click(first);
    await userEvent.paste('482913');
    const boxes = screen.getAllByRole('textbox') as HTMLInputElement[];
    expect(boxes.map((box) => box.value)).toEqual(['4', '8', '2', '9', '1', '3']);
    expect(complete).toEqual(['482913']);
  });

  it('moves focus back on Backspace from an empty box', async () => {
    render(<Harness />);
    const boxes = screen.getAllByRole('textbox');
    await userEvent.click(boxes[0]);
    await userEvent.type(boxes[0], '4');
    await userEvent.type(boxes[1], '{Backspace}');
    expect(boxes[0]).toHaveFocus();
  });
});
