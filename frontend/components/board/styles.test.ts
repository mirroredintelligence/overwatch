import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { contrastRatio } from '@/lib/a11y/contrast';

// The board's look is in CSS, which jsdom does not apply, so these tests read
// the shipped stylesheets and check the rules the prompt and the "Main" artboard fix.

function css(name: string): string {
  return readFileSync(resolve(__dirname, name), 'utf8').replace(/\/\*[\s\S]*?\*\//g, '');
}

function rule(source: string, selector: string): string {
  const match = new RegExp(`(?:^|\\n)\\s*${selector.replace('.', '\\.')}\\s*\\{([^}]*)\\}`).exec(source);
  // A missing rule is an empty one, so the test fails on its assertion.
  return match ? match[1] : '';
}

const tile = css('Tile.module.css');
const board = css('Board.module.css');
const tokens = readFileSync(resolve(__dirname, '../../app/tokens.css'), 'utf8');

const colours = new Map<string, string>();
for (const m of tokens.matchAll(/(--c-[\w-]+)\s*:\s*(#[0-9a-fA-F]{6})\s*;/g)) colours.set(m[1], m[2]);
for (const m of tile.matchAll(/(--tile-[\w-]+)\s*:\s*(#[0-9a-fA-F]{6})\s*;/g)) colours.set(m[1], m[2]);

// An unknown colour is an empty string, which has no contrast, so the test fails on its assertion.
function colour(name: string): string {
  return colours.get(name) ?? '';
}

const WHITE = '#FFFFFF';

describe('Tile borders and backgrounds (prompt, "Rules you need")', () => {
  it('accepting has a 3px --c-primary border', () => {
    expect(rule(tile, '.accepting')).toMatch(/border:\s*3px solid var\(--c-primary\)/);
  });

  it('limited has a 3px --c-limited border', () => {
    expect(rule(tile, '.limited')).toMatch(/border:\s*3px solid var\(--c-limited\)/);
  });

  it('not accepting has the #E9EDEF background and a --c-closed border', () => {
    expect(rule(tile, '.notAccepting')).toMatch(/border:\s*3px solid var\(--c-closed\)/);
    expect(rule(tile, '.notAccepting')).toMatch(/background:\s*var\(--tile-closed-bg\)/);
    expect(colour('--tile-closed-bg').toUpperCase()).toBe('#E9EDEF');
  });

  it('not updated has a dashed 3px --c-unknown border and a hatched background', () => {
    expect(rule(tile, '.notUpdated')).toMatch(/border:\s*3px dashed var\(--c-unknown\)/);
    expect(rule(tile, '.notUpdated')).toMatch(/background:\s*repeating-linear-gradient\(/);
  });

  it('over capacity has a 3px --c-surge border', () => {
    expect(rule(tile, '.overCapacity')).toMatch(/border:\s*3px solid var\(--c-surge\)/);
  });

  it('over capacity fills its bar with a striped purple, not a flat colour (a pattern as well as a colour)', () => {
    expect(rule(tile, '.overCapacity')).toMatch(/--tile-fill:\s*repeating-linear-gradient\(/);
  });

  it('out of hours has the #E9EDEF background and a 3px --c-closed border (W07)', () => {
    expect(rule(tile, '.outOfHours')).toMatch(/border:\s*3px solid var\(--c-closed\)/);
    expect(rule(tile, '.outOfHours')).toMatch(/background:\s*var\(--tile-closed-bg\)/);
    expect(rule(tile, '.outOfHours')).toMatch(/--tile-fill:\s*var\(--c-closed\)/);
  });

  it('the pending chip has its own border and a white background, so it reads on every tile (W07)', () => {
    expect(rule(tile, '.pending')).toMatch(/border:\s*2px solid/);
    expect(rule(tile, '.pending')).toMatch(/background:\s*Canvas/);
    expect(rule(tile, '.pending')).toMatch(/color:\s*var\(--c-ink\)/);
  });
});

describe('Tile size', () => {
  it('the big number is at least 72px (4.5rem on a 16px root)', () => {
    const size = /font-size:\s*([\d.]+)rem/.exec(rule(tile, '.number'));
    expect(size).not.toBeNull();
    expect(Number(size?.[1]) * 16).toBeGreaterThanOrEqual(72);
  });

  it('no text is below 16px (DEC-019)', () => {
    for (const m of tile.matchAll(/font-size:\s*([\d.]+)(rem|px)/g)) {
      const px = m[2] === 'rem' ? Number(m[1]) * 16 : Number(m[1]);
      expect(px).toBeGreaterThanOrEqual(16);
    }
  });
});

describe('Board layout', () => {
  it('has three columns on a wall screen and one on a phone', () => {
    expect(board).toMatch(/grid-template-columns:\s*repeat\(3,\s*minmax\(0,\s*1fr\)\)/);
    expect(board).toMatch(/grid-template-columns:\s*1fr\b/);
  });

  it('has no animation or transition (live changes are W06)', () => {
    expect(board + tile).not.toMatch(/\b(animation|transition)\s*:/);
  });
});

describe('Tile contrast (WCAG AA), from the shipped colours', () => {
  const surfaces: [string, string[]][] = [
    ['accepting', [WHITE]],
    ['limited', [WHITE]],
    ['over capacity', [WHITE]],
    ['not accepting', [colour('--tile-closed-bg')]],
    ['out of hours', [colour('--tile-closed-bg')]],
    ['not updated (both hatch colours)', [colour('--tile-hatch-a'), colour('--tile-hatch-b')]],
  ];

  it.each([
    ['accepting number', 'var-c-primary-dark', WHITE, 3],
    ['limited number', '--tile-limited-number', WHITE, 3],
    ['over capacity number', '--tile-surge-number', WHITE, 3],
  ])('%s is at least 3:1 (large text)', (_label, name, background, minimum) => {
    const foreground = colour(name === 'var-c-primary-dark' ? '--c-primary-dark' : name);
    expect(contrastRatio(foreground, background)).toBeGreaterThanOrEqual(minimum);
  });

  it('the not-accepting number is at least 3:1 on its background', () => {
    expect(contrastRatio(colour('--c-closed'), colour('--tile-closed-bg'))).toBeGreaterThanOrEqual(3);
  });

  it('the out-of-hours 0 is at least 3:1 on its background', () => {
    expect(rule(tile, '.outOfHours')).toMatch(/--tile-number:\s*var\(--c-closed\)/);
    expect(contrastRatio(colour('--c-closed'), colour('--tile-closed-bg'))).toBeGreaterThanOrEqual(3);
  });

  it('the pending chip text (--c-ink) is at least 4.5:1 on its white background', () => {
    expect(contrastRatio(colour('--c-ink'), WHITE)).toBeGreaterThanOrEqual(4.5);
  });

  it('the not-updated ? is at least 3:1 on both hatch colours', () => {
    for (const background of [colour('--tile-hatch-a'), colour('--tile-hatch-b')]) {
      expect(contrastRatio(colour('--c-unknown'), background)).toBeGreaterThanOrEqual(3);
    }
  });

  it.each(surfaces)('body text (--c-ink-2 and --c-muted) is at least 4.5:1 on %s', (_label, backgrounds) => {
    for (const background of backgrounds) {
      expect(contrastRatio(colour('--c-ink-2'), background)).toBeGreaterThanOrEqual(4.5);
      expect(contrastRatio(colour('--c-muted'), background)).toBeGreaterThanOrEqual(4.5);
    }
  });
});
