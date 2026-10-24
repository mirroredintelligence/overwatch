// WCAG 2.x contrast ratio between two six-digit hex colours, e.g. "#0B5C8C".
// Result is (L_light + 0.05) / (L_dark + 0.05), from 1 to 21.

function channelToLinear(value: number): number {
  const c = value / 255;
  return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
}

function relativeLuminance(hex: string): number {
  const digits = hex.replace(/^#/, '');
  const r = channelToLinear(parseInt(digits.slice(0, 2), 16));
  const g = channelToLinear(parseInt(digits.slice(2, 4), 16));
  const b = channelToLinear(parseInt(digits.slice(4, 6), 16));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

export function contrastRatio(fg: string, bg: string): number {
  const a = relativeLuminance(fg);
  const b = relativeLuminance(bg);
  const lighter = Math.max(a, b);
  const darker = Math.min(a, b);
  return (lighter + 0.05) / (darker + 0.05);
}
