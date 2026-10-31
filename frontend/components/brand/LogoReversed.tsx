import Image from 'next/image';
import { PRODUCT_NAME } from '@/lib/product';

// The reversed logo, for a dark background (the wall display's header): public/brand/overwatch-logo-reversed.svg
// carries its own blue field, white mark and white name. Same size rule and alt text as Logo (520 by 120).
export function LogoReversed({ height = 56 }: { height?: number }) {
  const width = Math.round((height * 520) / 120);
  return (
    <Image src="/brand/overwatch-logo-reversed.svg" alt={PRODUCT_NAME} width={width} height={height} unoptimized priority />
  );
}
