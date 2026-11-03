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
const chip = css('StatusChip.module.css');
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

  it('out of hours is a quiet tile (#EEF3F7, a solid 3px --c-unknown border), not the Not accepting tile (BoardQuiet)', () => {
    expect(rule(tile, '.outOfHours')).toMatch(/border:\s*3px solid var\(--c-unknown\)/);
    expect(rule(tile, '.outOfHours')).toMatch(/background:\s*var\(--tile-quiet-bg\)/);
    expect(rule(tile, '.outOfHours')).toMatch(/--tile-fill:\s*var\(--c-unknown\)/);
    expect(colour('--tile-quiet-bg').toUpperCase()).toBe('#EEF3F7');
    expect(rule(tile, '.outOfHours')).not.toMatch(/--c-closed|--tile-closed-bg/);
  });

  it('every tile has the card shadow and the 3px border of the artboard', () => {
    expect(rule(tile, '.tile')).toMatch(/box-shadow:\s*var\(--shadow-card\)/);
    expect(rule(tile, '.tile')).toMatch(/border-radius:\s*var\(--radius-card\)/);
  });

  it('the old-figure words are bold and --tile-limited-number coloured (stale figures)', () => {
    expect(rule(tile, '.old')).toMatch(/font-weight:\s*700/);
    expect(rule(tile, '.old')).toMatch(/color:\s*var\(--tile-limited-number\)/);
  });

  it('the pending chip has its own border and a white background, so it reads on every tile (W07)', () => {
    expect(rule(tile, '.pending')).toMatch(/border:\s*2px solid/);
    expect(rule(tile, '.pending')).toMatch(/background:\s*Canvas/);
    expect(rule(tile, '.pending')).toMatch(/color:\s*var\(--c-ink\)/);
  });
});

describe('Tile size', () => {
  const wall = /@media\s*\(min-width:\s*1600px\)\s*\{([\s\S]*)\}\s*$/.exec(tile)?.[1] ?? '';

  it('the big number is 42px on the board (BoardNormal) and at least 72px on a wall screen (WallBoard: 104px)', () => {
    const base = /font-size:\s*([\d.]+)rem/.exec(rule(tile, '.number'));
    expect(base).not.toBeNull();
    expect(Number(base?.[1]) * 16).toBeGreaterThanOrEqual(42);
    const onWall = /font-size:\s*([\d.]+)rem/.exec(rule(wall, '.number'));
    expect(onWall).not.toBeNull();
    expect(Number(onWall?.[1]) * 16).toBeGreaterThanOrEqual(72);
  });

  it('the tile border is 6px on a wall screen', () => {
    expect(rule(wall, '.tile')).toMatch(/border-width:\s*6px/);
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
    expect(board + tile + chip).not.toMatch(/\b(animation|transition)\s*:/);
  });
});

describe('StatusChip (BoardNormal, BoardQuiet, BoardDown)', () => {
  it('the four current states are filled pills with white text; not updated is a white pill with a dashed border', () => {
    expect(rule(chip, '.accepting')).toMatch(/background:\s*var\(--c-primary\)/);
    expect(rule(chip, '.limited')).toMatch(/background:\s*var\(--c-limited\)/);
    expect(rule(chip, '.notAccepting')).toMatch(/background:\s*var\(--c-closed\)/);
    expect(rule(chip, '.overCapacity')).toMatch(/background:\s*var\(--c-surge\)/);
    expect(rule(chip, '.notUpdated')).toMatch(/border:\s*2px dashed var\(--c-unknown\)/);
  });

  it('out of hours is a white pill with a solid ink border: neither filled like Not accepting nor dashed like Not updated', () => {
    expect(rule(chip, '.outOfHours')).toMatch(/border:\s*2px solid var\(--c-ink-2\)/);
    expect(rule(chip, '.outOfHours')).toMatch(/background:\s*Canvas/);
  });

  it('the Last known pill is dashed with an ink border', () => {
    expect(rule(chip, '.lastKnown')).toMatch(/border:\s*2px dashed var\(--c-ink\)/);
  });

  it.each([
    ['accepting', '--c-primary'],
    ['limited', '--c-limited'],
    ['not accepting', '--c-closed'],
    ['over capacity', '--c-surge'],
  ])('the %s word is at least 4.5:1 on its fill', (_label, name) => {
    expect(contrastRatio(WHITE, colour(name))).toBeGreaterThanOrEqual(4.5);
  });

  it('the not-updated, out-of-hours and Last known words are at least 4.5:1 on white', () => {
    expect(contrastRatio(colour('--c-ink-2'), WHITE)).toBeGreaterThanOrEqual(4.5);
    expect(contrastRatio(colour('--c-ink'), WHITE)).toBeGreaterThanOrEqual(4.5);
  });

  it('draws no text below 16px', () => {
    for (const m of chip.matchAll(/font-size:\s*([\d.]+)(rem|px)/g)) {
      const px = m[2] === 'rem' ? Number(m[1]) * 16 : Number(m[1]);
      expect(px).toBeGreaterThanOrEqual(16);
    }
  });
});

describe('Tile contrast (WCAG AA), from the shipped colours', () => {
  const surfaces: [string, string[]][] = [
    ['accepting', [WHITE]],
    ['limited', [WHITE]],
    ['over capacity', [WHITE]],
    ['not accepting', [colour('--tile-closed-bg')]],
    ['out of hours', [colour('--tile-quiet-bg')]],
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

  it('the out-of-hours 0 is at least 4.5:1 on its quiet background', () => {
    expect(rule(tile, '.outOfHours')).toMatch(/--tile-number:\s*var\(--c-ink-2\)/);
    expect(contrastRatio(colour('--c-ink-2'), colour('--tile-quiet-bg'))).toBeGreaterThanOrEqual(4.5);
  });

  it('the old-figure words are at least 4.5:1 on white and on the quiet tile', () => {
    expect(contrastRatio(colour('--tile-limited-number'), WHITE)).toBeGreaterThanOrEqual(4.5);
    expect(contrastRatio(colour('--tile-limited-number'), colour('--tile-quiet-bg'))).toBeGreaterThanOrEqual(4.5);
  });

  it('the pending chip text (--c-ink) is at least 4.5:1 on its white background', () => {
    expect(contrastRatio(colour('--c-ink'), WHITE)).toBeGreaterThanOrEqual(4.5);
  });

  it('the not-updated ? is --c-ink-2 and at least 4.5:1 on both hatch colours', () => {
    expect(rule(tile, '.notUpdated')).toMatch(/--tile-number:\s*var\(--c-ink-2\)/);
    for (const background of [colour('--tile-hatch-a'), colour('--tile-hatch-b')]) {
      expect(contrastRatio(colour('--c-ink-2'), background)).toBeGreaterThanOrEqual(4.5);
    }
  });

  it.each(surfaces)('body text (--c-ink-2 and --c-muted) is at least 4.5:1 on %s', (_label, backgrounds) => {
    for (const background of backgrounds) {
      expect(contrastRatio(colour('--c-ink-2'), background)).toBeGreaterThanOrEqual(4.5);
      expect(contrastRatio(colour('--c-muted'), background)).toBeGreaterThanOrEqual(4.5);
    }
  });
});
