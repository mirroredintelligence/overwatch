import { readFileSync, readdirSync, statSync } from 'node:fs';
import { extname, join, resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { contrastRatio } from '@/lib/a11y/contrast';

const css = readFileSync(resolve(__dirname, 'tokens.css'), 'utf8');
const designSystem = readFileSync(resolve(__dirname, '../../docs/design/design-system.md'), 'utf8');

// Every "--name: value;" declaration. The lookbehind stops --c-primary matching
// inside --c-primary-dark, and stops var(--x) uses counting as declarations.
const DECLARATION = /(?<![\w-])(--[\w-]+)\s*:\s*([^;]+);/g;

function declarations(source: string): Map<string, string> {
  const found = new Map<string, string>();
  for (const match of source.matchAll(DECLARATION)) {
    found.set(match[1], match[2].trim());
  }
  return found;
}

// The base :root block starts and ends at column 0. The reduced-motion override
// is a separate block that closes at column 0 too, so the two never mix.
const BASE = /^:root \{([\s\S]*?)^\}/m.exec(css)?.[1] ?? '';
const REDUCED = /^@media \(prefers-reduced-motion: reduce\) \{([\s\S]*?)^\}/m.exec(css)?.[1] ?? '';
const declared = declarations(BASE);
const reducedDeclared = declarations(REDUCED);

const squash = (value: string): string => value.replace(/\s+/g, '');

// The design system's token tables (section 5.2) are the source. Rows look like
// "| `--dur-press` | 140 ms | ..." and "| `--ease-out` | `cubic-bezier(...)` | ...".
const SPEC = new Map<string, string>();
for (const line of designSystem.split('\n')) {
  const row = /^\| `(--[\w-]+)` \| (.+?) \|/.exec(line);
  if (row) SPEC.set(row[1], squash(row[2].replace(/`/g, '')));
}

const DURATIONS = ['--dur-press', '--dur-tip', '--dur-menu', '--dur-sheet', '--dur-state', '--dur-onboard'];
const MOVEMENT_DURATIONS = ['--dur-press', '--dur-tip', '--dur-menu', '--dur-sheet', '--dur-onboard'];
const EASINGS = ['--ease-out', '--ease-in-out', '--ease-drawer', '--ease-hover'];

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
  ['--c-line', '#D5DCE0'],
  ['--c-bg', '#F4F6F5'],
  ['--c-tint', '#E9F0F4'],
  ['--c-amber-tint', '#F8EFE0'],
  ['--radius', '8px'],
  ['--btn-h', '52px'],
  ['--chip-h', '48px'],
  ['--focus', '3px solid #14232B'],
];

const SPACING: [string, string][] = [
  ['--space-1', '4px'],
  ['--space-2', '8px'],
  ['--space-3', '12px'],
  ['--space-4', '16px'],
  ['--space-5', '20px'],
  ['--space-6', '28px'],
  ['--space-7', '40px'],
  ['--space-8', '56px'],
];

// Design system section 3 as tightened by DEC-1365: one scale (14, 16, 18, 24, display), body 16 px, caption 14 px.
const TYPE_ROLES: [string, string, string, string, string][] = [
  // [role, size, line height, weight, tracking]
  ['display', 'clamp(2rem, 4.5vw, 3rem)', '1.05', '700', '-0.02em'],
  ['heading', '24px', '1.25', '700', '-0.01em'],
  ['title', '18px', '1.3', '700', '0'],
  ['body', '16px', '1.5', '400', '0'],
  ['label', '16px', '1.4', '700', '0.01em'],
  ['caption', '14px', '1.4', '400', '0.01em'],
];

// Source files the no-ease-in rule scans. Test files are excluded: they name the rule.
function sourceFiles(dir: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir)) {
    if (entry === 'node_modules' || entry === '.next') continue;
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) {
      out.push(...sourceFiles(path));
    } else if (['.ts', '.tsx', '.css', '.js', '.mjs'].includes(extname(entry)) && !/\.test\.tsx?$/.test(entry)) {
      out.push(path);
    }
  }
  return out;
}

describe('tokens.css', () => {
  it.each(TOKENS)('declares %s as %s', (name, value) => {
    expect(declared.get(name)).toBe(value);
  });

  it('sets the page font to the Atkinson variable from layout.tsx', () => {
    expect(css).toMatch(/html\s*\{[^}]*font-family:\s*var\(--font-atkinson\)/);
  });

  it('declares exactly the 13 colour tokens, unchanged from F09', () => {
    const colours = [...declared.keys()].filter((name) => name.startsWith('--c-')).sort();
    expect(colours).toEqual(TOKENS.filter(([name]) => name.startsWith('--c-')).map(([name]) => name).sort());
    expect(colours).toHaveLength(13);
  });
});

describe('motion tokens', () => {
  // --dur-sheet is set by DEC-019 (280 ms), which overrides the 320 ms in the design system table.
  it.each(DURATIONS.filter((name) => name !== '--dur-sheet'))('%s equals its design system duration', (name) => {
    expect(SPEC.has(name)).toBe(true);
    expect(squash(declared.get(name) ?? '')).toBe(SPEC.get(name));
  });

  it.each(EASINGS)('%s equals its design system curve', (name) => {
    expect(SPEC.has(name)).toBe(true);
    expect(squash(declared.get(name) ?? '')).toBe(SPEC.get(name));
  });

  it('zeroes every movement duration under prefers-reduced-motion', () => {
    for (const name of MOVEMENT_DURATIONS) {
      expect(reducedDeclared.get(name), name).toBe('0ms');
    }
  });

  it('leaves --dur-state out of the reduced-motion block, at 240 ms', () => {
    expect(reducedDeclared.has('--dur-state')).toBe(false);
    expect(declared.get('--dur-state')).toBe('240ms');
  });

  it('overrides only the movement durations in the reduced-motion block', () => {
    expect([...reducedDeclared.keys()].sort()).toEqual([...MOVEMENT_DURATIONS].sort());
  });

  it('keeps UI durations under 300 ms, except onboarding (480 ms)', () => {
    for (const name of DURATIONS.filter((n) => n !== '--dur-onboard')) {
      const ms = Number.parseInt(declared.get(name) ?? '', 10);
      expect(ms, name).toBeLessThanOrEqual(300);
    }
    expect(declared.get('--dur-onboard')).toBe('480ms');
  });

  it('sets --dur-sheet to 280 ms per DEC-019 (was 320 ms; under the 300 ms rule)', () => {
    expect(declared.get('--dur-sheet')).toBe('280ms');
  });

  it('uses only the approved easing curves', () => {
    const approved = new Set(EASINGS.map((name) => SPEC.get(name)));
    for (const name of EASINGS) {
      expect(approved.has(squash(declared.get(name) ?? '')), name).toBe(true);
    }
  });

  it('never uses ease-in on UI (ease-in-out is allowed)', () => {
    const pattern = /\bease-in\b(?!-out)/;
    const offenders = sourceFiles(resolve(__dirname, '..')).filter((file) =>
      pattern.test(readFileSync(file, 'utf8')),
    );
    expect(offenders).toEqual([]);
  });
});

describe('spacing, radius and type tokens', () => {
  it.each(SPACING)('declares %s as %s', (name, value) => {
    expect(declared.get(name)).toBe(value);
  });

  it('declares the card radius (12px) and the chip radius (6px), DEC-1365', () => {
    expect(declared.get('--radius-card')).toBe('12px');
    expect(declared.get('--radius-chip')).toBe('6px');
  });

  it.each(TYPE_ROLES)('declares the %s type role from section 3', (role, size, lineHeight, weight, tracking) => {
    expect(declared.get(`--type-${role}-size`)).toBe(size);
    expect(declared.get(`--type-${role}-lh`)).toBe(lineHeight);
    expect(declared.get(`--type-${role}-weight`)).toBe(weight);
    expect(declared.get(`--type-${role}-tracking`)).toBe(tracking);
  });

  it('sets the root font size to 16px and the body to the body role', () => {
    expect(css).toMatch(/html\s*\{[^}]*font-size:\s*16px;/);
    expect(css).toMatch(/body\s*\{[^}]*font-size:\s*var\(--type-body-size\)/);
  });

  it('provides a tabular-nums utility class for number columns', () => {
    expect(css).toMatch(/\.tabular-nums\s*\{[^}]*font-variant-numeric:\s*tabular-nums/);
  });
});

// The redesign shell's additions (DEC-1326): their own block, after the base one, so nothing above changed.
describe('the shell tokens (DEC-1326)', () => {
  // Up to the wall's pin block (DEC-1365), which restores the earlier values for the wall only.
  const added = declarations(css.slice(css.indexOf('The redesign shell (DEC-1326)'), css.indexOf("[data-surface='wall']")));

  it.each([
    ['--c-rail', '#0B2A3D'],
    ['--c-rail-ink', '#B9D0DC'],
    ['--c-ground', '#F0F3F4'],
    ['--shadow-card', '0 1px 2px rgb(20 35 43 / 0.06), 0 2px 8px rgb(20 35 43 / 0.04)'],
    ['--shadow-lift', '0 8px 24px rgb(11 42 61 / 0.16), 0 1px 3px rgb(11 42 61 / 0.08)'],
  ])('%s is %s', (name, value) => {
    expect(added.get(name)).toBe(value);
  });

  it('has the spring as a cubic-bezier, with a linear() spring where the browser has it', () => {
    expect(css).toMatch(/--ease-spring: cubic-bezier\(0\.34, 1\.56, 0\.64, 1\);/);
    expect(css).toMatch(/@supports \(transition-timing-function: linear\(0, 1\)\) \{\s*:root \{\s*--ease-spring: linear\(0, 0\.009/);
  });

  it('zeroes the layout-morph duration under reduced motion', () => {
    expect(css).toMatch(/@media \(prefers-reduced-motion: reduce\) \{\s*:root \{\s*--dur-stage: 0ms;/);
  });
});

// DEC-1365: the tightening pass keeps every size a person reads, every touch target, and the wall board as it was.
describe('the tightening pass (DEC-1365)', () => {
  const px = (name: string) => Number.parseFloat(declared.get(name) ?? '');
  const shell = declarations(css.slice(css.indexOf('The redesign shell (DEC-1326)')));

  it('keeps body text at 14 px or more and every type role on one scale', () => {
    const roles = ['body', 'label', 'caption', 'title', 'heading'];
    for (const role of roles) expect(px(`--type-${role}-size`), role).toBeGreaterThanOrEqual(14);
    const sizes = new Set(roles.map((role) => px(`--type-${role}-size`)));
    expect([...sizes].sort((a, b) => a - b)).toEqual([14, 16, 18, 24]);
  });

  it('keeps the touch targets (52 px buttons, 48 px chips)', () => {
    expect(px('--btn-h')).toBe(52);
    expect(px('--chip-h')).toBe(48);
  });

  it('uses smaller radii: controls 8 px, cards 12 px, chips 12 px at most', () => {
    expect(px('--radius')).toBeLessThanOrEqual(8);
    expect(px('--radius-card')).toBeLessThanOrEqual(12);
    expect(px('--radius-chip')).toBeLessThanOrEqual(12);
  });

  it('has a hairline card border token and calmer shadows (no blur above 24 px)', () => {
    expect(declared.get('--border-card')).toBe('1px solid var(--c-line)');
    for (const name of ['--shadow-card', '--shadow-lift']) {
      for (const m of (shell.get(name) ?? '').matchAll(/\d+px \d+px (\d+)px/g)) expect(Number(m[1])).toBeLessThanOrEqual(24);
    }
  });

  it('pins the wall board to the values it had before the pass (the wall is unchanged)', () => {
    const wall = /^\[data-surface='wall'\] \{([\s\S]*?)^\}/m.exec(css)?.[1] ?? '';
    const pinned = declarations(wall);
    const before: [string, string][] = [
      ['--radius', '14px'],
      ['--radius-card', '24px'],
      ['--radius-chip', '9999px'],
      ['--radius-panel', '18px'],
      ['--space-5', '24px'],
      ['--space-6', '32px'],
      ['--space-7', '48px'],
      ['--space-8', '64px'],
      ['--c-line', '#DDE3E6'],
      ['--c-tint', '#E3F1F8'],
      ['--c-amber-tint', '#FFF1DC'],
      ['--c-ground', '#EEF2F3'],
      ['--shadow-card', '0 1px 2px rgb(20 35 43 / 0.06), 0 10px 28px rgb(20 35 43 / 0.07)'],
      ['--shadow-lift', '0 18px 48px rgb(11 42 61 / 0.22), 0 2px 6px rgb(11 42 61 / 0.08)'],
      ['--type-display-size', 'clamp(2rem, 5vw, 3.5rem)'],
      ['--type-heading-size', '28px'],
      ['--type-body-size', '18px'],
      ['--type-label-size', '17px'],
    ];
    for (const [name, value] of before) expect(pinned.get(name), name).toBe(value);
  });
});

// DEC-1365 part B: the attention glow tokens. The rules that use them are in attention.test.ts.
describe('the glow tokens (DEC-1365)', () => {
  // The shell block and the glow block, before the wall pin block (which restores the old ground for the wall).
  const glow = declarations(css.slice(css.indexOf('The redesign shell (DEC-1326)'), css.indexOf("[data-surface='wall']")));

  it('declares the stale (blue) and over-capacity (red) glow colours, each 3:1 against the page ground and white', () => {
    expect(glow.get('--glow-stale')).toBe('#2F80ED');
    expect(glow.get('--glow-over')).toBe('#D92D20');
    for (const name of ['--glow-stale', '--glow-over']) {
      for (const ground of ['#FFFFFF', glow.get('--c-ground') ?? '']) {
        expect(contrastRatio(glow.get(name) ?? '', ground), `${name} on ${ground}`).toBeGreaterThanOrEqual(3);
      }
    }
  });

  it('has a pulse period of at least 2 seconds', () => {
    const period = /^([\d.]+)s$/.exec(glow.get('--glow-period') ?? '');
    expect(period).not.toBeNull();
    expect(Number(period?.[1])).toBeGreaterThanOrEqual(2);
  });
});
