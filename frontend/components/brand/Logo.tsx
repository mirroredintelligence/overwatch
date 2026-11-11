import { PRODUCT_NAME } from '@/lib/product';

// The product logo: the mark and the name, from public/brand. The alt text is the product name, so a heading that
// holds only this image is still named by it. The logo is 520 by 120. A plain image, not next/image: next/image puts
// `style="color:transparent"` on the element, which the content security policy (style-src 'self' 'nonce-...')
// refuses, so every page logged an error. The file is a small SVG and was already served unoptimised.
export function Logo({ height = 56 }: { height?: number }) {
  const width = Math.round((height * 520) / 120);
  // eslint-disable-next-line @next/next/no-img-element
  return <img src="/brand/overwatch-logo.svg" alt={PRODUCT_NAME} width={width} height={height} />;
}
