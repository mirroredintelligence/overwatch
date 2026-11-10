import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import dialogJson from './dialog.json';
import { countsLine, derivedValue, holds, joinCounts, renderTurn, type DialogContext } from './dialog';

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

describe('dialog renderer (WS-DLG)', () => {
  it('WS-DLG-T01 every example in dialog.json renders its echo, reply, chips and chip intents', () => {
    const failures: string[] = [];
    for (const row of dialogJson.examples) {
      try {
        const got = renderTurn(row.intent, row.context as DialogContext, { withEcho: row.withEcho ?? true });
        if (got === null) {
          failures.push(`${row.id}: turn is null`);
          continue;
        }
        const labels = got.chips.map((chip) => chip.label);
        const intents = got.chips.map((chip) => chip.intent);
        if (JSON.stringify(got.echo) !== JSON.stringify(row.echo)) {
          failures.push(`${row.id} echo: want ${JSON.stringify(row.echo)}, got ${JSON.stringify(got.echo)}`);
        }
        if (got.reply !== row.reply) {
          failures.push(`${row.id} reply: want ${row.reply}, got ${got.reply}`);
        }
        if (JSON.stringify(labels) !== JSON.stringify(row.chips)) {
          failures.push(`${row.id} chips: want ${JSON.stringify(row.chips)}, got ${JSON.stringify(labels)}`);
        }
        if (JSON.stringify(intents) !== JSON.stringify(row.chipIntents)) {
          failures.push(`${row.id} chipIntents: want ${JSON.stringify(row.chipIntents)}, got ${JSON.stringify(intents)}`);
        }
      } catch (error) {
        failures.push(`${row.id} threw: ${errorMessage(error)}`);
      }
    }
    expect(failures).toEqual([]);
  });

  it('WS-DLG-T02 every error in dialog.json throws an Error with exactly the given message', () => {
    const failures: string[] = [];
    for (const row of dialogJson.errors) {
      try {
        renderTurn(row.intent, row.context as DialogContext);
        failures.push(`${row.id}: did not throw`);
      } catch (error) {
        if (!(error instanceof Error)) {
          failures.push(`${row.id}: threw a non-Error ${String(error)}`);
        } else if (error.message !== row.throws) {
          failures.push(`${row.id}: threw ${error.message}, want ${row.throws}`);
        }
      }
    }
    expect(failures).toEqual([]);
  });

  it('WS-DLG-T03 holds: literal keys need strict equality; gt and present need the right type; a missing key never holds except present false', () => {
    expect(holds({}, {})).toBe(true);
    expect(holds({}, { count: 3 })).toBe(true);

    expect(holds({ count: 0 }, { count: 0 })).toBe(true);
    expect(holds({ count: 0 }, { count: '0' })).toBe(false);
    expect(holds({ count: 0 }, { count: false })).toBe(false);
    expect(holds({ count: 0 }, {})).toBe(false);
    expect(holds({ tab: 'under' }, { tab: 'under' })).toBe(true);
    expect(holds({ tab: 'under' }, { tab: 'pressure' })).toBe(false);

    expect(holds({ count: { gt: 0 } }, { count: 1 })).toBe(true);
    expect(holds({ count: { gt: 0 } }, { count: 0 })).toBe(false);
    expect(holds({ count: { gt: 0 } }, { count: '5' })).toBe(false);
    expect(holds({ count: { gt: 0 } }, { count: true })).toBe(false);
    expect(holds({ count: { gt: 0 } }, {})).toBe(false);

    expect(holds({ name: { present: true } }, { name: 'x' })).toBe(true);
    expect(holds({ name: { present: true } }, { name: '' })).toBe(false);
    expect(holds({ name: { present: true } }, { name: 1 })).toBe(false);
    expect(holds({ name: { present: true } }, {})).toBe(false);

    expect(holds({ name: { present: false } }, {})).toBe(true);
    expect(holds({ name: { present: false } }, { name: '' })).toBe(true);
    expect(holds({ name: { present: false } }, { name: 1 })).toBe(true);
    expect(holds({ name: { present: false } }, { name: 'x' })).toBe(false);
  });

  it('WS-DLG-T04 derivedValue: one for a source of 1, other for 0 and 2, undefined when the source is missing, for every derived key', () => {
    const failures: string[] = [];
    for (const [name, rule] of Object.entries(dialogJson.derived)) {
      const cases: Array<[number | undefined, string | undefined]> = [
        [1, rule.one],
        [0, rule.other],
        [2, rule.other],
        [undefined, undefined],
      ];
      for (const [value, want] of cases) {
        const ctx = (value === undefined ? {} : { [rule.from]: value }) as DialogContext;
        const got = derivedValue(name, ctx);
        if (got !== want) {
          failures.push(`${name} with source ${String(value)}: want ${String(want)}, got ${String(got)}`);
        }
      }
    }
    expect(failures).toEqual([]);
  });

  it('WS-DLG-T05 renderTurn returns null for advisor.new-search and throws for an unknown intent id', () => {
    expect(renderTurn('advisor.new-search', {})).toBeNull();
    expect(() => renderTurn('nope', {})).toThrow(new Error('dialog: no turn for nope'));
  });

  it('WS-DLG-T06 withEcho false skips the echo placeholders (row D26); withEcho true with a missing placeholder throws', () => {
    const quiet = renderTurn('advisor.service', {}, { withEcho: false });
    expect(quiet?.echo).toBeNull();
    expect(quiet?.reply).toBe('Here is the service. If the call allows, check that its figure is current.');

    const quietNeed = renderTurn('advisor.intake.need', {}, { withEcho: false });
    expect(quietNeed?.echo).toBeNull();
    expect(quietNeed?.reply).toBe('What does the patient need, and by when?');

    expect(() => renderTurn('advisor.intake.need', {})).toThrow('dialog: missing {age}');
  });

  it('WS-DLG-T07 the runtime dialog.json deep-equals docs/design/workspaces/dialog.json', () => {
    const designPath = path.resolve(process.cwd(), '..', 'docs/design/workspaces/dialog.json');
    const design = JSON.parse(fs.readFileSync(designPath, 'utf8')) as unknown;
    expect(dialogJson).toEqual(design);
  });

  it('WS-DLG-T08 joinCounts: none gives empty, one gives it, two use "and", three or more use commas then "and"', () => {
    expect(joinCounts([])).toBe('');
    expect(joinCounts(['a'])).toBe('a');
    expect(joinCounts(['a', 'b'])).toBe('a and b');
    expect(joinCounts(['a', 'b', 'c'])).toBe('a, b and c');
  });

  it('WS-DLG-T09 countsLine lists the non-zero statuses in order with their words', () => {
    expect(countsLine({ accepting: 2, limited: 1, 'over-capacity': 1 })).toBe('2 accepting, 1 limited and 1 over capacity');
    expect(countsLine({ accepting: 1 })).toBe('1 accepting');
    expect(countsLine({})).toBe('');
    expect(countsLine({ accepting: 0, limited: 0, 'not-accepting': 0, 'over-capacity': 0, 'not-updated': 0 })).toBe('');
    expect(countsLine({ 'not-accepting': 3, 'not-updated': 1 })).toBe('3 not accepting and 1 not updated');
  });
});
