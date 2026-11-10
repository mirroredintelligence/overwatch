import dialogJson from './dialog.json';

// The assistant's fixed dialog: templates, variants and chips from dialog.json, no model.
// The Python reference in docs/design/workspaces/check.py gives the same answer for every example.

export type DialogContext = Readonly<Record<string, string | number | boolean | null | undefined>>;
export type ChipSpec = { label: string; intent: string; params?: Record<string, string> };
export type RenderedTurn = { echo: string | null; reply: string; card: string | null; summaryBox: boolean; chips: ChipSpec[] };
export type CountStatus = 'accepting' | 'limited' | 'not-accepting' | 'over-capacity' | 'not-updated';

type Derived = { from: string; one: string; other: string };
type Variant = { when: Readonly<Record<string, unknown>>; reply: string };
type Chip = { label: string; intent: string; params?: Record<string, string>; when?: Readonly<Record<string, unknown>> };
type Turn = { echo: string | null; card: string | null; summaryBox: boolean; variants: Variant[]; chips: Chip[] };
type DialogSpec = { derived: Readonly<Record<string, Derived>>; turns: Readonly<Record<string, Turn | null>> };

const spec = dialogJson as unknown as DialogSpec;

const COUNT_WORDS: ReadonlyArray<readonly [CountStatus, string]> = [
  ['accepting', 'accepting'],
  ['limited', 'limited'],
  ['not-accepting', 'not accepting'],
  ['over-capacity', 'over capacity'],
  ['not-updated', 'not updated'],
];

function hasOwn(object: object, key: string): boolean {
  return Object.prototype.hasOwnProperty.call(object, key);
}

// A plural word chosen from a count in the context: 'one' for exactly 1, 'other' for any other number.
export function derivedValue(name: string, ctx: DialogContext): string | undefined {
  if (!hasOwn(spec.derived, name)) return undefined;
  const rule = spec.derived[name];
  const source = ctx[rule.from];
  if (typeof source !== 'number') return undefined;
  return source === 1 ? rule.one : rule.other;
}

function lookup(name: string, ctx: DialogContext): string {
  const value = ctx[name];
  if (value !== undefined && value !== null) return String(value);
  const derived = derivedValue(name, ctx);
  if (derived !== undefined) return derived;
  throw new Error(`dialog: missing {${name}}`);
}

function fill(template: string, ctx: DialogContext): string {
  return template.replace(/\{(\w+)\}/g, (_match, name: string) => lookup(name, ctx));
}

export function holds(when: Readonly<Record<string, unknown>>, ctx: DialogContext): boolean {
  return Object.entries(when).every(([key, want]) => {
    const have = ctx[key];
    if (typeof want === 'object' && want !== null) {
      const rule = want as Record<string, unknown>;
      if ('gt' in rule) return typeof have === 'number' && typeof rule.gt === 'number' && have > rule.gt;
      if ('present' in rule) return (typeof have === 'string' && have !== '') === rule.present;
      return false;
    }
    return have === want;
  });
}

export function joinCounts(parts: readonly string[]): string {
  if (parts.length <= 1) return parts[0] ?? '';
  return `${parts.slice(0, -1).join(', ')} and ${parts[parts.length - 1]}`;
}

export function countsLine(tally: Readonly<Partial<Record<CountStatus, number>>>): string {
  const parts = COUNT_WORDS.flatMap(([status, word]) => {
    const n = tally[status] ?? 0;
    return n > 0 ? [`${n} ${word}`] : [];
  });
  return joinCounts(parts);
}

export function renderTurn(intentId: string, ctx: DialogContext, opts?: { withEcho?: boolean }): RenderedTurn | null {
  if (!hasOwn(spec.turns, intentId)) throw new Error(`dialog: no turn for ${intentId}`);
  const turn = spec.turns[intentId];
  if (turn === null) return null;
  const withEcho = opts?.withEcho ?? true;
  // The echo is filled first, so a missing echo placeholder throws before the reply is considered.
  const echo = turn.echo !== null && withEcho ? fill(turn.echo, ctx) : null;
  const variant = turn.variants.find((candidate) => holds(candidate.when, ctx));
  if (!variant) throw new Error(`dialog: no variant for ${intentId}`);
  const reply = fill(variant.reply, ctx);
  const chips: ChipSpec[] = turn.chips
    .filter((chip) => holds(chip.when ?? {}, ctx))
    .map((chip) => ({
      label: fill(chip.label, ctx),
      intent: chip.intent,
      ...(chip.params ? { params: chip.params } : {}),
    }));
  return { echo, reply, card: turn.card, summaryBox: turn.summaryBox, chips };
}
