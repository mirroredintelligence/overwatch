import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

// DEC-1365 part B: the attention treatment on the advisor-side board and the service cards. The look is CSS,
// which jsdom does not apply, so these tests read the shipped stylesheet and check the rules the decision fixes.

const source = readFileSync(resolve(__dirname, 'attention.css'), 'utf8');
const css = source.replace(/\/\*[\s\S]*?\*\//g, '');

function blocks(sheet: string): { selector: string; body: string }[] {
  const out: { selector: string; body: string }[] = [];
  for (const m of sheet.matchAll(/([^{}]+)\{([^{}]*)\}/g)) out.push({ selector: m[1].trim(), body: m[2] });
  return out;
}

function rule(sheet: string, selector: string): string {
  return blocks(sheet).find((b) => b.selector === selector)?.body ?? '';
}

const reduced = /@media \(prefers-reduced-motion: reduce\) \{([\s\S]*?)\n\}/.exec(css)?.[1] ?? '';

describe('attention classes (DEC-1365)', () => {
  it('has a stale glow in --glow-stale and an over-capacity glow in --glow-over, from the tokens only', () => {
    expect(rule(css, '.attention-stale::after')).toMatch(/var\(--glow-stale\)/);
    expect(rule(css, '.attention-over::after')).toMatch(/var\(--glow-over\)/);
    expect(css).not.toMatch(/#[0-9a-fA-F]{3,8}\b|rgb\(/);
  });

  it('pulses the glow slowly: the period is the token (2 s or more), the curve is ease-in-out, and the opacity never reaches 0', () => {
    for (const name of ['.attention-stale::after', '.attention-over::after']) {
      expect(rule(css, name)).toMatch(/animation:\s*attention-pulse var\(--glow-period\) ease-in-out infinite/);
    }
    const keyframes = /@keyframes attention-pulse \{([\s\S]*?)\n\}/.exec(css)?.[1] ?? '';
    const opacities = [...keyframes.matchAll(/opacity:\s*([\d.]+)/g)].map((m) => Number(m[1]));
    expect(opacities.length).toBeGreaterThanOrEqual(2);
    expect(Math.min(...opacities)).toBeGreaterThanOrEqual(0.4);
    expect(Math.max(...opacities)).toBeLessThanOrEqual(1);
    // Never flashing: one smooth cycle, no step timing.
    expect(css).not.toMatch(/steps\(/);
  });

  it('stops the animation under prefers-reduced-motion and leaves a static ring at full strength', () => {
    expect(reduced).toMatch(/\.attention-stale::after,\s*\.attention-over::after\s*\{[^}]*animation:\s*none/);
    expect(reduced).toMatch(/opacity:\s*1/);
  });

  it('the limited and not-accepting emphasis is static: no animation at all', () => {
    expect(rule(css, '.attention-limited::after')).toMatch(/box-shadow:/);
    expect(rule(css, '.attention-limited::after')).not.toMatch(/animation/);
  });

  it('never changes what the card says: no size, display, visibility, order, colour or fill on the card or its content', () => {
    for (const { selector, body } of blocks(css)) {
      if (/^[\d%,.\s]+$|^(from|to)$/.test(selector) || selector.startsWith('@')) continue;
      expect(body, selector).not.toMatch(/font-size|display\s*:|visibility|\border\s*:|(^|[;\s])color\s*:|background|transform|scale|width|height|filter/);
    }
  });

  it('draws the glow on a layer that takes no clicks', () => {
    expect(rule(css, '.attention::after')).toMatch(/pointer-events:\s*none/);
    expect(rule(css, '.attention')).toMatch(/position:\s*relative/);
  });
});
