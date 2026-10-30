import { describe, expect, it } from 'vitest';
import {
  CODE_LENGTH_MESSAGE,
  CODE_REQUIRED_MESSAGE,
  formatCode,
  NAME_REQUIRED_MESSAGE,
  parseCode,
  parseLocation,
  parseName,
  SCREEN_LABEL_MAX,
} from './model';

describe('formatCode', () => {
  it('shows six digits as two groups of three, as the ScreenPairing artboard does', () => {
    expect(formatCode('482913')).toBe('482 913');
    expect(formatCode('000123')).toBe('000 123');
  });

  it.each(['', '48291', '4829133', '48291a', '482 913', '٤٨٢٩١٣', '482913\n'])(
    'shows nothing for %j: a code the back end would not give is never put on a wall',
    (value) => {
      expect(formatCode(value)).toBe('');
    },
  );
});

describe('parseCode', () => {
  it('takes the code as typed or as shown, with or without the space', () => {
    expect(parseCode('482913')).toEqual({ ok: true, value: '482913' });
    expect(parseCode('482 913')).toEqual({ ok: true, value: '482913' });
    expect(parseCode('  482   913  ')).toEqual({ ok: true, value: '482913' });
    expect(parseCode('482 913')).toEqual({ ok: true, value: '482913' });
  });

  it.each(['', '   ', '\t'])('asks for the code when it is %j', (input) => {
    expect(parseCode(input)).toEqual({ ok: false, error: CODE_REQUIRED_MESSAGE });
  });

  it.each(['48291', '4829133', '48 29 1', '48291a', 'abcdef', '482-913', '٤٨٢٩١٣', '482913​'])(
    'says the code has 6 numbers when it is %j',
    (input) => {
      expect(parseCode(input)).toEqual({ ok: false, error: CODE_LENGTH_MESSAGE });
    },
  );

  it('uses the words of the prompt', () => {
    expect(CODE_REQUIRED_MESSAGE).toBe('Enter the code shown on the screen');
    expect(CODE_LENGTH_MESSAGE).toBe('The code has 6 numbers');
    expect(NAME_REQUIRED_MESSAGE).toBe('Enter a name for the screen');
  });
});

describe('parseName and parseLocation', () => {
  it('trims a name, and asks for one when it is empty', () => {
    expect(parseName('  Control room  ')).toEqual({ ok: true, value: 'Control room' });
    expect(parseName('')).toEqual({ ok: false, error: NAME_REQUIRED_MESSAGE });
    expect(parseName('   ')).toEqual({ ok: false, error: NAME_REQUIRED_MESSAGE });
  });

  it('allows a name of as many characters as the back end does, and no more', () => {
    expect(SCREEN_LABEL_MAX).toBe(60);
    expect(parseName('a'.repeat(60)).ok).toBe(true);
    expect(parseName('a'.repeat(61))).toEqual({ ok: false, error: 'Use 60 characters or fewer.' });
    expect(parseName(`  ${'a'.repeat(60)}  `).ok).toBe(true);
  });

  it('refuses control characters in a name', () => {
    expect(parseName('Control\u0007room').ok).toBe(false);
    expect(parseName('Control\nroom').ok).toBe(false);
  });

  it('takes no where-it-is as none, and a where-it-is as typed, trimmed', () => {
    expect(parseLocation('')).toEqual({ ok: true, value: null });
    expect(parseLocation('   ')).toEqual({ ok: true, value: null });
    expect(parseLocation(' Ward 4 corridor ')).toEqual({ ok: true, value: 'Ward 4 corridor' });
    expect(parseLocation('a'.repeat(61))).toEqual({ ok: false, error: 'Use 60 characters or fewer.' });
  });

  it('refuses anything that is not text', () => {
    for (const bad of [undefined, null, 7, {}, []]) {
      expect(parseName(bad as never).ok).toBe(false);
      expect(parseCode(bad as never).ok).toBe(false);
    }
    expect(parseLocation(undefined as never)).toEqual({ ok: true, value: null });
    expect(parseLocation(7 as never).ok).toBe(false);
  });
});
