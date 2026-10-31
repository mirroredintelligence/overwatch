import Image from 'next/image';
import { PRODUCT_NAME } from '@/lib/product';

// The product logo: the mark and the name, from public/brand. The alt text is the product name, so a heading that
// holds only this image is still named by it. The logo is 520 by 120.
export function Logo({ height = 56 }: { height?: number }) {
  const width = Math.round((height * 520) / 120);
  return <Image src="/brand/overwatch-logo.svg" alt={PRODUCT_NAME} width={width} height={height} unoptimized priority />;
}
