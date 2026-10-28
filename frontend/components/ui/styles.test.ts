import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const NAMES = ['Button', 'Chip', 'OptionButton', 'NumberStepper', 'Banner', 'Card'];

// "No hard-coded colours outside tokens.css references": strip comments, then
// no hex, rgb(), hsl() or named colour may appear in a component stylesheet.
describe('W03 stylesheets', () => {
  for (const name of NAMES) {
    it(`${name}.module.css exists and uses tokens for colour`, () => {
      const css = readFileSync(resolve(__dirname, `${name}.module.css`), 'utf8').replace(/\/\*[\s\S]*?\*\//g, '');
      expect(css).not.toMatch(/#[0-9a-fA-F]{3,8}\b/);
      expect(css).not.toMatch(/\b(rgb|rgba|hsl|hsla)\(/);
      expect(css).not.toMatch(/:\s*(white|black|red|blue|green|gray|grey)\b/);
      expect(css).toMatch(/var\(--c-/);
    });
  }

  it('Button sizes and focus come from the spec', () => {
    const css = readFileSync(resolve(__dirname, 'Button.module.css'), 'utf8');
    expect(css).toMatch(/min-height:\s*var\(--btn-h\)/);
    expect(css).toMatch(/outline:\s*var\(--focus\)/);
    expect(css).toMatch(/outline-offset:\s*2px/);
  });

  it('Chip is 48px high and round', () => {
    const css = readFileSync(resolve(__dirname, 'Chip.module.css'), 'utf8');
    expect(css).toMatch(/min-height:\s*var\(--chip-h\)/);
    expect(css).toMatch(/border-radius:\s*var\(--radius-chip\)/);
  });
});
