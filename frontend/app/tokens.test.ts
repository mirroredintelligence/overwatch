import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const css = readFileSync(resolve(__dirname, 'tokens.css'), 'utf8');

// Reads the value a custom property is declared with on :root. The lookbehind
// stops --c-primary matching inside --c-primary-dark.
function declaredValue(name: string): string | undefined {
  const match = new RegExp(`(?<![\w-])${name}\s*:\s*([^;]+);`).exec(css);
  return match?.[1].trim();
}

const TOKENS: [string, string][] = [
  ['--c-primary', '#0B5C8C'],
  ['--c-primary-dark', '#0B3F61'],
  ['--c-limited', '#A34700'],
  ['--c-closed', '#3A4750'],
  ['--c-surge', '#6B2C91'],
  ['--c-unknown', '#6B7B83'],
  ['--c-ink', '#14232B'],
  ['--c-ink-2', '#26343B'],
  ['--c-muted', '#44555D'],
  ['--c-line', '#DDE3E6'],
  ['--c-bg', '#F4F6F5'],
  ['--c-tint', '#E3F1F8'],
  ['--c-amber-tint', '#FFF1DC'],
  ['--radius', '14px'],
  ['--btn-h', '52px'],
  ['--chip-h', '48px'],
  ['--focus', '3px solid #14232B'],
];

describe('tokens.css', () => {
  it.each(TOKENS)('declares %s as %s', (name, value) => {
    expect(declaredValue(name)).toBe(value);
  });

  it('sets the page font to the Atkinson variable from layout.tsx', () => {
    expect(css).toMatch(/html\s*\{[^}]*font-family:\s*var\(--font-atkinson\)/);
  });
});
