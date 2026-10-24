import { readFileSync, readdirSync, statSync } from 'node:fs';
import { extname, join, resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

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
  ['--c-line', '#DDE3E6'],
  ['--c-bg', '#F4F6F5'],
  ['--c-tint', '#E3F1F8'],
  ['--c-amber-tint', '#FFF1DC'],
  ['--radius', '14px'],
  ['--btn-h', '52px'],
  ['--chip-h', '48px'],
  ['--focus', '3px solid #14232B'],
];

const SPACING: [string, string][] = [
  ['--space-1', '4px'],
  ['--space-2', '8px'],
  ['--space-3', '12px'],
  ['--space-4', '16px'],
  ['--space-5', '24px'],
  ['--space-6', '32px'],
  ['--space-7', '48px'],
  ['--space-8', '64px'],
];

// Design system section 3. Caption is 14 px in the table; see DEC-015.
const TYPE_ROLES: [string, string, string, string, string][] = [
  // [role, size, line height, weight, tracking]
  ['display', 'clamp(2rem, 5vw, 3.5rem)', '1.05', '700', '-0.02em'],
  ['heading', '28px', '1.2', '700', '-0.01em'],
  ['title', '22px', '1.3', '700', '0'],
  ['body', '18px', '1.5', '400', '0'],
  ['label', '17px', '1.4', '700', '0.01em'],
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
  it.each(DURATIONS)('%s equals its design system duration', (name) => {
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

  it('keeps UI durations under 300 ms, with --dur-sheet as the one stated exception (DEC-015)', () => {
    for (const name of DURATIONS.filter((n) => n !== '--dur-onboard' && n !== '--dur-sheet')) {
      const ms = Number.parseInt(declared.get(name) ?? '', 10);
      expect(ms, name).toBeLessThanOrEqual(300);
    }
    expect(declared.get('--dur-sheet')).toBe('320ms');
    expect(declared.get('--dur-onboard')).toBe('480ms');
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

  it('declares the card radius (24px) and the chip radius (full round)', () => {
    expect(declared.get('--radius-card')).toBe('24px');
    expect(declared.get('--radius-chip')).toBe('9999px');
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
