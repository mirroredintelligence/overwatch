import { render } from '@testing-library/react';
import { renderToString } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { StyledDiv } from './Styled';

describe('StyledDiv', () => {
  it('writes no style attribute in the markup a server sends (the policy refuses one)', () => {
    expect(renderToString(<StyledDiv css={{ width: '40%' }} data-x="1" />)).not.toMatch(/style=/);
  });

  it('sets the value on the element from script once it exists, and follows a change', () => {
    const { container, rerender } = render(<StyledDiv css={{ width: '40%', '--gap': '2px' } as React.CSSProperties} data-x="1" />);
    const element = container.querySelector('[data-x]') as HTMLElement;
    expect(element.style.width).toBe('40%');
    expect(element.style.getPropertyValue('--gap')).toBe('2px');
    rerender(<StyledDiv css={{ width: '75%' }} data-x="1" />);
    expect(element.style.width).toBe('75%');
    expect(element.style.getPropertyValue('--gap')).toBe('');
  });
});
