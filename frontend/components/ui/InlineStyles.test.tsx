import { act, render, waitFor } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { InlineStyles } from './InlineStyles';

// The applier copies a `data-css` attribute onto the element as styles, through the CSS object model
// (the strict style policy blocks style attributes). It also follows an element that is added or changed.
describe('InlineStyles', () => {
  it('copies the values of data-css onto the element, with camel case turned to dashes and custom properties kept', async () => {
    const { container } = render(
      <>
        <InlineStyles />
        <div data-testid="target" data-css={JSON.stringify({ flexGrow: 3, gridTemplateColumns: '1fr 2fr', '--share': 0.5 })} />
      </>,
    );
    const target = container.querySelector('[data-testid="target"]') as HTMLElement;
    await waitFor(() => expect(target.style.flexGrow).toBe('3'));
    expect(target.style.gridTemplateColumns).toBe('1fr 2fr');
    expect(target.style.getPropertyValue('--share')).toBe('0.5');
  });

  it('follows a change to data-css and an element that is added later', async () => {
    const { container, rerender } = render(
      <>
        <InlineStyles />
        <div data-testid="target" data-css={JSON.stringify({ width: '10%' })} />
      </>,
    );
    rerender(
      <>
        <InlineStyles />
        <div data-testid="target" data-css={JSON.stringify({ width: '60%' })} />
      </>,
    );
    const target = container.querySelector('[data-testid="target"]') as HTMLElement;
    await waitFor(() => expect(target.style.width).toBe('60%'));
    await act(async () => {
      const added = document.createElement('span');
      added.setAttribute('data-css', JSON.stringify({ left: '25%' }));
      container.appendChild(added);
    });
    await waitFor(() => expect((container.querySelector('span') as HTMLElement).style.left).toBe('25%'));
  });

  it('ignores a value that is not JSON, and one that is not a plain object', async () => {
    const { container } = render(
      <>
        <InlineStyles />
        <div data-testid="bad" data-css="not json" />
        <div data-testid="list" data-css={JSON.stringify([1, 2])} />
      </>,
    );
    await waitFor(() => expect(container.querySelector('[data-testid="bad"]')).not.toBeNull());
    expect((container.querySelector('[data-testid="bad"]') as HTMLElement).getAttribute('style')).toBeNull();
    expect((container.querySelector('[data-testid="list"]') as HTMLElement).getAttribute('style')).toBeNull();
  });
});
