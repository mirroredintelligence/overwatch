import type { AxeMatchers } from 'vitest-axe';

// Adds toHaveNoViolations to Vitest's expect() types (vitest-axe 0.1 augments
// the old Vi namespace only).
declare module 'vitest' {
  // The empty body is intentional: the interface only merges AxeMatchers in.
  // eslint-disable-next-line @typescript-eslint/no-empty-object-type, @typescript-eslint/no-unused-vars
  interface Matchers<T = unknown> extends AxeMatchers {}
}
