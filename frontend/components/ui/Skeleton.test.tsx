import { renderToString } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { Skeleton, SkeletonRows } from './Skeleton';

// The content security policy refuses a style attribute in the markup the server sends, so a placeholder's
// width travels as a data attribute that the stylesheet reads.
describe('Skeleton', () => {
  it('puts no style attribute in the markup, whatever width it is given', () => {
    const html = renderToString(
      <>
        <Skeleton shape="title" width="46%" />
        <Skeleton shape="line" width="33.6%" />
        <SkeletonRows count={3} />
      </>,
    );
    expect(html).not.toMatch(/style=/);
  });

  it('rounds the width to a whole percent and keeps it between 1 and 100', () => {
    expect(renderToString(<Skeleton width="33.6%" />)).toContain('data-w="34"');
    expect(renderToString(<Skeleton width="250%" />)).toContain('data-w="100"');
    expect(renderToString(<Skeleton width="0%" />)).toContain('data-w="1"');
  });

  it('has no width attribute when none is given', () => {
    expect(renderToString(<Skeleton />)).not.toContain('data-w');
  });
});
