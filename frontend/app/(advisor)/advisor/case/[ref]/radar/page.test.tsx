import { describe, expect, it } from 'vitest';
import RadarPage from './page';

// The Radar address is kept for bookmarks and case steps, and lands on the Map with the coverage layer on (DEC-1372).
describe('the old radar address', () => {
  it('redirects to the Map with the "Who covers this area" layer on', async () => {
    let digest = '';
    try {
      await RadarPage({ params: Promise.resolve({ ref: '4821' }) });
    } catch (error) {
      digest = String((error as { digest?: string }).digest);
    }
    expect(digest).toMatch(/^NEXT_REDIRECT;(replace|push);\/advisor\/case\/4821\/map\?layer=coverage;/);
  });

  it('keeps an odd case reference safe in the address', async () => {
    let digest = '';
    try {
      await RadarPage({ params: Promise.resolve({ ref: 'a b/c' }) });
    } catch (error) {
      digest = String((error as { digest?: string }).digest);
    }
    expect(digest).toContain('/advisor/case/a%20b%2Fc/map?layer=coverage');
  });
});
